# Architecture — ListingLens Copilot

This is the deep-dive document for engineers who clicked into the repo. The [README](README.md) covers the pitch + eval numbers; this covers the *why* behind each choice.

## Table of contents

1. [The state machine](#1-the-state-machine)
2. [Why three nodes instead of one](#2-why-three-nodes-instead-of-one)
3. [The tool layer (and the dual interface)](#3-the-tool-layer-and-the-dual-interface)
4. [Evaluation methodology](#4-evaluation-methodology)
5. [SSE streaming + the trace panel](#5-sse-streaming--the-trace-panel)
6. [Reuse story — wrapping v1 inside v2 tools](#6-reuse-story--wrapping-v1-inside-v2-tools)
7. [Design tradeoffs called out](#7-design-tradeoffs-called-out)
8. [Production migration path](#8-production-migration-path)

---

## 1. The state machine

The agent is a LangGraph v1 `StateGraph` with four nodes and one tiny pass-through helper. Topology:

```
START → planner → executor ─→ tools ──┐
                     ▲                 │
                     └─────────────────┘
                     │
                     ▼
                synthesizer ──→ END
                     │
                     │  if confidence < 0.5 AND replans_done < 1
                     ▼
                bump_replan → executor (one extra loop only)
```

**State shape** ([backend/agent/schemas.py](backend/agent/schemas.py)):

```python
class AgentState(TypedDict, total=False):
    asin: str                          # set at entry, read by every tool
    query: str
    product_name: str
    messages: Annotated[list[AnyMessage], add_messages]
    iterations: int                    # tool-call counter, cap = 8
    query_type: QueryType              # filled by Planner
    plan: list[str]                    # remaining tool names; Executor consumes
    tools_called: list[str]            # for trace + dedup
    recommendation: Optional[Recommendation]   # filled by Synthesizer
    replans_done: int                  # caps the low-confidence re-loop at 1
    image_urls: list[str]              # optional, from the UI with the asin
    main_index: Optional[int]          # which supplied image is the main one
    audit_id: Optional[str]            # an image audit the UI already ran
    context: str                       # prior turns / pinned report (agent/context.py)
    synthesis_degraded: bool           # the Recommendation was assembled locally
    executor_degraded: bool            # the Executor gave up on a tool call
```

`asin` is set once at entry from the API request and read by every tool from state — never parsed out of the natural-language query. This is the "ASIN-scoped UX" decision: the user picks a product in the dropdown first, then asks freeform questions. Same pattern as `/chat`.

`add_messages` is LangGraph's built-in reducer that appends new messages to the list across node calls — so every node sees the full conversation history.

---

## 2. Why three nodes instead of one

The simpler design is a single ReAct loop: one prompt that does *everything* (classify the query, decide which tools, react to results, synthesize the answer). I implemented this first in [Stage 2](#) and it worked. So why split into three nodes?

**The single-node prompt has to do too much.** Any LLM has a finite attention budget. A single prompt that contains "classify this query AND pick tools AND react to results AND output a structured Recommendation" forces the model to multi-task. Mistakes correlate: when the planning is bad, the execution is bad, and the synthesis paper-overs it.

**Three smaller prompts beat one big one.** Each node has a focused, smaller system prompt. Failure modes are diagnosable:

- If the **Planner** outputs a wrong `query_type` or empty `tool_sequence`, that's a planning failure. The trace shows it before any tool fires.
- If the **Executor** repeatedly skips planned tools, that's a discipline failure in the executor prompt. Fix one prompt; don't touch the planner or synthesizer.
- If the **Synthesizer** produces a confident `go` from thin evidence, that's a calibration failure in the synth prompt. Same — surgical fix.

**Per-node prompts are in [backend/agent/prompts.py](backend/agent/prompts.py).** Three constants/functions:
- `PLANNER_SYSTEM_PROMPT` (static — one-shot classification + plan)
- `executor_system_prompt(asin, product_name, plan, tools_called, is_replan)` (dynamic — sees plan state)
- `SYNTHESIZER_SYSTEM_PROMPT` (static — transcript → Recommendation)

### Node-by-node

#### Planner — [backend/agent/nodes/planner.py](backend/agent/nodes/planner.py)

- **Job:** classify the query, propose tool sequence.
- **Input:** `asin`, `product_name`, `query`.
- **Output:** `Plan` (Pydantic): `query_type ∈ {launch, returns, improve, unknown}`, `tool_sequence: list[ToolName]`, `rationale: str`.
- **How:** one `instructor.from_groq` call with `response_model=Plan`. instructor guarantees the model output validates against the Pydantic schema (max_retries=2 if it doesn't).
- **Fallback:** keyword-based `_fallback_plan(query)` if the structured call ever fails. Returns a reasonable default per query type so the graph can still proceed.
- **Side effect on state:** emits a single `AIMessage` tagged `name="planner"` with a one-line summary so the trace + LangSmith log read cleanly.

#### Executor — [backend/agent/nodes/executor.py](backend/agent/nodes/executor.py)

- **Job:** pick the next tool call (or stop). One tool per invocation.
- **Input:** the full message history + the remaining `plan` and `tools_called` lists from state.
- **Output:** one `AIMessage` that either:
  - has `tool_calls` (LangGraph's `ToolNode` then runs them, the result comes back as `ToolMessage`), or
  - has just `content` (a finish signal — routes to Synthesizer).
- **How:** a `ChatGroq` LLM with the 6 tools bound via `bind_tools(tools, parallel_tool_calls=False)`. The serial constraint is critical — see [Design tradeoffs](#7-design-tradeoffs-called-out).
- **Modes:** the system prompt has two paths — **normal** (follow the plan) and **re-plan** (Synthesizer asked for more evidence; pick unused tools).
- **Iteration cap:** state's `iterations` counter increments on every tool call. The routing edge after the executor sends it to Synthesizer if `iterations >= MAX_TOOL_ITERATIONS` (8).

#### `tools` (LangGraph prebuilt `ToolNode`)

Not really a "node" in the design sense — it's LangGraph's stock helper that takes the latest message's `tool_calls`, dispatches to the matching `@tool`-decorated function, and emits one `ToolMessage` per call. The one custom piece is `handle_tool_error` ([graph.py](backend/agent/graph.py)): a tool that raises (a rate-limited RAG chain, a FAISS load failure, a vision-service timeout) becomes an evidence gap in its `ToolMessage` instead of aborting the run.

#### Synthesizer — [backend/agent/nodes/synthesizer.py](backend/agent/nodes/synthesizer.py)

- **Job:** convert the trajectory (the full message history) into a structured `Recommendation`.
- **Input:** the full message log.
- **Output:** a `Recommendation` Pydantic object: `decision`, `confidence`, `summary`, `reasoning_steps`, `evidence`, `risks`, `suggested_next_actions`, `evidence_gaps`.
- **How:** `_build_transcript(...)` flattens the conversation into a compact text form (tool calls + tool results + executor thoughts), then an `instructor.from_groq` call with `response_model=Recommendation`, run through `resilient_call` on the agent model chain. If the whole chain fails, the node assembles a recommendation locally from the tool results and sets `synthesis_degraded`, so the UI never shows it as a real verdict.
- **Why a separate node instead of a final ReAct turn:** ReAct can emit unstructured prose. We want a typed, machine-validated payload that the frontend can render without parsing. `instructor` + Pydantic = no JSON-parsing errors at the API boundary.

#### `bump_replan` (pass-through)

Increments `replans_done` before re-entering the Executor. Explicit so the LangSmith trace shows when a re-plan happens — `if rec.confidence < 0.5 and replans_done < 1` triggers it. Capped at one extra loop to prevent infinite re-planning.

---

## 3. The tool layer (and the dual interface)

Six tools live in [backend/mcp_server/tools/](backend/mcp_server/tools/). Each is **two things at once**:

1. A **plain Python function** importable via `from backend.mcp_server.tools.review_qa import review_qa`. Used directly by the agent code, the eval harness, and unit tests. Fast iteration — no protocol overhead.
2. An **MCP-server tool** exposed over stdio by [backend/mcp_server/server.py](backend/mcp_server/server.py) (mcp 2.x `MCPServer`). Used when an external MCP client (Claude Desktop, Cursor) connects. `tests/test_mcp_server.py` checks it imports and serves the same six tools as the agent.

Same functions, two surfaces, so the agent and the MCP server can't drift into different implementations. The surfaces differ in one way: the MCP tools still expose `max_results` and `days`, which the agent's closures fix at 5 and 90 (see [No optional numeric parameters](#no-optional-numeric-parameters-on-tools)).

Per-tool surface:

| Tool | File | Inputs | Output | Underlying |
|---|---|---|---|---|
| `review_qa` | [review_qa.py](backend/mcp_server/tools/review_qa.py) | `asin: str, question: str` | `{answer, sources[], n_sources}` | v1's [`ask_question()`](src/rag_chatbot.py) over FAISS; chain cached per ASIN |
| `predict_return_risk` | [return_risk.py](backend/mcp_server/tools/return_risk.py) | `asin: str` | `{risk_score, risk_label, risk_pct, confidence, explanation}` | v1's [`run_fusion_pipeline()`](src/fusion.py) (XGBoost) |
| `competitor_search` | [competitor.py](backend/mcp_server/tools/competitor.py) | `asin: str` | `{category, n_results, competitors[]}` (each w/ title, brand, price, rating, top_complaints) | Seed data in `backend/data/mock_market_data.json` |
| `price_history` | [price.py](backend/mcp_server/tools/price.py) | `asin: str` | `{daily_prices[90], min/max/avg, volatility, key_events}` | Deterministic synthesis from seed (sinusoidal + event injection); same ASIN → same curve |
| `trend_signal` | [trends.py](backend/mcp_server/tools/trends.py) | `asin: str` (or `category`) | `{months[12], values[12], trend_direction, yoy_change_pct}` | Seed per category |
| `image_audit` | [image_audit.py](backend/mcp_server/tools/image_audit.py) | `asin: str` (+ the request's images, injected from state) | per-image rule verdicts against Amazon's main-image requirements | A separate vision service; deterministic checks, not a model judgement |

When the LangGraph agent binds tools, it wraps each MCP tool in a per-ASIN closure ([graph.py:_build_tools_for_asin](backend/agent/graph.py)). The closure has the ASIN baked in, so the LLM never has to supply it — it just passes the semantic arg (`question` for review_qa, no args for the others; `image_audit` reads the request's images from state through LangGraph's `InjectedState`). That dropped a class of failure modes where the model would send `"max_results": "5"` (string) instead of `5` (int).

---

## 4. Evaluation methodology

Three independent axes. The current headline is the repeated-runs launch series in the [README](README.md#headline-numbers): full agent `eval/reports/2026-09-23-launch-full-k1` and `2026-09-25-launch-full-k2`; no-tool baseline `2026-09-27-`, `2026-09-28-` and `2026-10-01-launch-notool-k*`. Methodology summary in [eval/README.md](eval/README.md).

### Axis 1: output quality (LLM-as-judge)

[eval/judges.py](eval/judges.py). Four DeepEval `GEval` metrics, each scoring 0.0-1.0:

| Metric | What it checks |
|---|---|
| `decision_correctness` | Does the agent's `decision` field match the gold `expected_decision`? 1.0 = exact match, 0.5 = directionally similar, 0.0 = confidently wrong |
| `evidence_relevance` | Do the cited evidence snippets cover the gold `expected_evidence_themes`? |
| `anti_hallucination` | Are the agent's claims supported by its cited snippets? It sees only the agent's own snippets, never the raw tool outputs, so it measures internal consistency, not grounding |
| `completeness` | Does the recommendation address all critical aspects: decision, reasoning, next actions, risks? |

**Judge scores are kept out of the headline**: `evidence_relevance` is shown the expected decision, and `anti_hallucination` never sees the tool outputs, so neither measures what its name says yet.

**Judge model: Claude Haiku 4.5** (Anthropic, `claude-haiku-4-5-20251001` — see [eval/judges.py](eval/judges.py)). Different model family than the agent — explicitly to avoid the "model graded its own homework" bias. Easily swapped to OpenAI's `gpt-4o-mini` via `JUDGE_PROVIDER=openai`.

### Axis 2: trajectory correctness

[eval/trajectory_eval.py](eval/trajectory_eval.py). Pure Python, no LLM. For each query:

```
precision      = |expected ∩ actual| / |actual|
recall         = |expected ∩ actual| / |expected|
F1             = 2 * P * R / (P + R)
ordering_match = (first actual tool == first expected tool)
score          = F1 + (0.1 if ordering_match else 0)
```

Trajectory is *more diagnostic* than the final answer. If the agent called the wrong tools, the answer is wrong by accident even when it sounds plausible. In the two kept full-agent runs of the launch series, trajectory F1 was 0.830 and 0.816 (precision 0.791 / 0.814, recall 0.910 / 0.840), but the first tool matched the gold set's first tool on only 38.5% of rows.

### Axis 3: operational metrics

In [eval/run_eval.py](eval/run_eval.py): per-query wall-clock latency, error rate, error types. Tokens/cost tracking is on the to-do list (the LangChain callback hooks need to be wired through).

### The gold set

[eval/gold_set.jsonl](eval/gold_set.jsonl). 39 hand-crafted queries:

- 13 launch, 11 returns, 15 improve. **Only launch is scored**: `go` / `no_go` / `needs_more_data` is launch-decision vocabulary, and on the other types `go` just means "the agent answered" ([run_eval.py](eval/run_eval.py))
- All 12 supported ASINs exercised (2-4 queries each)
- Decision distribution: 25 `go` / 9 `needs_more_data` / 5 `no_go`; the launch rows alone are 6 `needs_more_data` / 5 `no_go` / 2 `go`
- Per-entry schema: `id`, `asin`, `product_name`, `query`, `query_type`, `expected_decision`, `expected_tools`, `expected_evidence_themes`, `notes`

Each query was authored such that the expected behavior is grounded in the actual NLP features cached in `data/processed/features_*.json`. For example, Ring Doorbell's "What's driving negative reviews?" gold expects evidence around customer service (17.3% of its mentions negative after the 2026-09-23 feature fixes; 44.8% before them), setup, and connectivity — because the v1 NLP pipeline already surfaced those as the top complaint topics.

### Baselines

[eval/baselines.py](eval/baselines.py) defines two, both producing the same `AgentOutput` shape so the eval treats them uniformly:

- **`no_tool`** — the same LLM with no tools: two calls, a plain answer and then a structured one. The "minimum useful" floor.
- **`single_tool`** — the agent with only `review_qa`. Shows the lift from adding the other five tools.

Both have been run (`2026-09-21-no-tool-judged`, `2026-09-22-single-tool-judged`), and `no_tool` ran three more times on the launch rows. Result: the full agent's launch accuracy (5/13, right in both of its runs) doesn't beat `no_tool` (6/13 in every run, all `needs_more_data`, which is exactly the constant floor); exact McNemar p = 1.0.

### CI eval

[.github/workflows/eval-on-pr.yml](.github/workflows/eval-on-pr.yml) runs a 5-query stratified smoke eval (`--limit 5 --no-judge --output-tag pr-smoke`) on PRs that touch the agent's code, and comments the report table in the PR. The job fails if any row errors or degrades.

---

## 5. SSE streaming + the trace panel

`POST /agent/query` and `POST /assistant/query` in [app.py](app.py) return a Server-Sent Events stream. The live UI uses `/assistant/query`, which adds a `kind` event first, an `answer` event in quick mode, and accepts follow-up `history` and a `pinned` report. Each agent phase emits an event the frontend renders in a live timeline.

**Backend side** — [backend/agent/graph.py:run_agent_streaming](backend/agent/graph.py) wraps `compiled.astream(stream_mode="updates")`. LangGraph yields `{node_name: state_delta}` after each node finishes. `_delta_to_events()` translates each delta into one or more frontend-friendly events:

| Event | Emitted from | Payload |
|---|---|---|
| `started` | top of run | `{asin, product_name, query}` |
| `node_started` | planner, executor, synthesizer — sent when the node finishes, just before `node_completed` (`astream` only reports finished nodes) | `{node, label}` |
| `plan_ready` | planner | `{query_type, plan: [tool_names]}` |
| `tool_call` | executor | `{tool, args}` |
| `tool_result` | tools | `{tool, result_preview}` (truncated to 1200 chars) |
| `executor_thought` | executor | `{content}` |
| `node_completed` | planner, executor, synthesizer exit | `{node}` |
| `replan` | bump_replan | `{reason}` |
| `recommendation` | synthesizer | full `Recommendation` JSON, plus `degraded`, `synthesis_degraded` and `executor_degraded` flags |
| `error` | exception in any node | `{message}` |
| `done` | normal stream end | `{}` |

**Frontend side** — the live `/assistant` page streams through [frontend/components/assistant/assistantStore.ts](frontend/components/assistant/assistantStore.ts) (the older `/agent` page, [frontend/app/agent/page.tsx](frontend/app/agent/page.tsx), works the same way). Both use `fetch` + `ReadableStream` (not the browser's built-in `EventSource` because that's GET-only and we POST a query body). A small inline async iterator (`readSSE`) parses event frames and yields `{event, data}` pairs.

The `TracePanel` component renders one row per event with per-event icons (Lucide). The "currently in flight" loader spinner shows only on the **most recent event while the stream is still active** — once a newer event arrives or the stream ends, prior rows flip from spinner to checkmark. (This was an iteration after the first version had every node_started row spinning forever.)

**Mock endpoint** — there's also `POST /agent/query/mock` that streams a canned trace from [backend/agent/mock_stream.py](backend/agent/mock_stream.py) with realistic delays. Same SSE shape as the live endpoint. Used during frontend development to avoid burning Groq tokens. The `/agent` page uses it unless `NEXT_PUBLIC_AGENT_LIVE=true`; the live `/assistant` page always calls the real endpoint.

---

## 6. Reuse story — wrapping v1 inside v2 tools

v1 is the foundation; v2 doesn't replace it. Concretely:

- v1's [`src/rag_chatbot.py:ask_question()`](src/rag_chatbot.py) is wrapped by `review_qa` in [backend/mcp_server/tools/review_qa.py](backend/mcp_server/tools/review_qa.py). The chain (FAISS + Groq) is built once per ASIN and cached in a module-level dict — repeated agent iterations on the same ASIN don't pay the FAISS-load cost again.
- v1's [`src/fusion.py:run_fusion_pipeline()`](src/fusion.py) is wrapped by `predict_return_risk`. Reads precomputed features from `data/processed/features_{asin}.json`; no NLP recompute.
- The XGBoost model trained on v1's synthetic-proxy labels is what the agent calls. The model architecture stays identical to v1 — only the call site changes.
- The 12 ASINs in v1's `src/ingest.py:SUPPORTED_ASINS` are also the 12 ASINs the agent operates on. No separate catalog.
- v1's `/chat` endpoint is untouched and still serves grounded RAG responses with citations. v2 added `/agent/query` alongside; both live in [app.py](app.py).

This matters for two reasons:
1. **Demo narrative.** "I extended my RAG project into an agent" reads stronger in interviews than "I built two separate projects."
2. **Stability.** The v1 deploy at [/chat](https://listinglens.hetprajapati.me/chat) keeps working with zero risk of breakage. Render's free tier serves both v1 and v2 endpoints from the same Python process.

---

## 7. Design tradeoffs called out

### Model tiering and per-model rate buckets

Groq has decommissioned the models under this project three times — Llama 4 Scout, then `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` when the entire Llama family was removed. Every model ID now lives in one place, [src/llm_config.py](src/llm_config.py), and `python -m scripts.doctor` validates each pin against Groq's live catalog. That turns the next deprecation from a nine-file scavenger hunt into a one-line change.

The tiering is a **load-balancing** decision, not only a quality one. Groq rate-limits per model (8000 TPM each), verified empirically: burning `gpt-oss-120b` down to 4992 remaining tokens left `gpt-oss-20b` untouched at 7923. So three hot paths get three independent buckets:

| Stage | Env var | Model | Why |
|---|---|---|---|
| Planner, Synthesizer, Brief | `AGENT_MODEL` | `openai/gpt-oss-120b` | 1–2 calls/run, quality-sensitive |
| Executor loop | `EXECUTOR_MODEL` | `openai/gpt-oss-20b` | 3–6 short calls/run |
| `review_qa` RAG + `/chat` | `GROQ_MODEL` | `qwen/qwen3.8-27b` | **must** be separate — the Executor calls `review_qa` mid-run, so a shared bucket makes one agent run rate-limit itself |

That third row is the subtle one, and it was the cause of the 429s in `eval/reports/2026-07-18-full.md`.

### Fallback chains — why a deprecation no longer causes an outage

Pinning one model per stage means the app is always one Groq deprecation away from a total outage. That is precisely how it broke three times. So every stage now declares an **ordered chain** in `src/llm_config.py`, and `resilient_call()` walks it:

| Stage | Chain |
|---|---|
| agent | `gpt-oss-120b` → `gpt-oss-20b` → `qwen3.8-27b` |
| executor | `gpt-oss-20b` → `gpt-oss-safeguard-20b` → `qwen3.8-27b` |
| rag | `qwen3.8-27b` → `gpt-oss-20b` → `gpt-oss-120b` |
| intent | `gpt-oss-20b` → `qwen3.8-27b` → `gpt-oss-120b` |

Failover triggers on:
- a decommissioned model (404 `model_not_found`);
- a rate limit (429, or a 413 "request too large" for that model's per-minute limit). A short per-minute 429 that survives the SDK's own `retry-after` wait is first waited out once on the same model (up to 10 s), because the SDK's whole-second wait can land a moment early;
- malformed tool calls, after one same-model retry;
- an unavailable provider (timeout, dropped connection, 5xx), only while the stage is inside its 45 s deadline.

Nothing else fails over. A bad API key or a request *we* malformed propagates immediately rather than being retried against three models in a row and masking the real bug.

Measured free-tier limits differ by model: 8,000 tokens per minute for `gpt-oss-120b`, `gpt-oss-20b` and `qwen3.8-27b`, but 2,000 for `gpt-oss-safeguard-20b`, so most executor turns are "request too large" on the executor's first fallback.

Verified by pinning **every** stage to the dead `llama-3.3-70b-versatile` / `llama-3.1-8b-instant`: the agent still returned a complete recommendation in 9.5s, logging each failover and pointing at `scripts/doctor.py`.

Only four free Groq models support both tool-calling and structured output — `gpt-oss-120b`, `gpt-oss-20b`, `gpt-oss-safeguard-20b`, `qwen3.8-27b`. `allam-2-7b`, `groq/compound` and `groq/compound-mini` reject a `tools` payload outright, so they cannot serve any stage here.

### Output-token limits are a separate, tighter cap

Groq enforces **output** tokens per minute (OTPM) separately from the input TPM cap, and rejects a request up front based on the output it *estimates* from `max_tokens` — not on what the model actually emits. `qwen3.8-27b` has OTPM=1000, so a RAG chain at `max_tokens=1024` claims the entire minute's budget and 429s before it runs. The RAG chain therefore caps at 512 (the prompt asks for "under 150 words" ≈ 200 tokens), and every client sets `request_timeout`, because langchain otherwise retries a 429 with backoff and no deadline — which hangs the uvicorn worker thread rather than returning an error.

### `reasoning_effort` per stage

The gpt-oss models are reasoning models: they emit a hidden reasoning trace before answering, billed against the completion budget. `reasoning_effort="low"` cut total tokens 280 → 171 on an identical prompt, and end-to-end agent latency from a 62.9s p50 to ~9s at the time. (The 2026-09 eval runs, with more tools per run and free-tier rate limits, measured p50 42–48 s.) Low for the planner, executor and intent stages; medium for the synthesizer and brief, where the output is the user-facing recommendation. The RAG chain sets none.

Two consequences worth knowing:

- **`max_tokens` must leave headroom for reasoning.** At `max_tokens=64` a tool-selection call spent the whole budget thinking and returned `finish_reason="length"` with no tool call at all. The executor runs at 2048 for this reason; the RAG chain stays at 512 because of the OTPM cap above.
- **`.content` is empty on a pure tool-call turn**, with the rationale in `additional_kwargs["reasoning_content"]`. Anything rendering the Executor's thinking must read both — hence `thought_text()` in `src/llm_config.py`, used by the SSE trace in `graph.py` and the Synthesizer's transcript builder.

### `parallel_tool_calls=False`

Kept, but for a different reason than originally: the routing edge in `graph.py` assumes one tool call per turn, and the trace panel reads better serially. The graph already loops the Executor, so serial calling is functionally equivalent. (The original justification — keeping Llama models off their native XML function syntax — no longer applies.)

### Tolerant `Evidence.tool` and Executor retries

Two robustness measures that reasoning models made necessary:

- The gpt-oss models are inconsistent about the evidence field name. Across three retries of one query they emitted `tool_name`, `tool`, and `source`. Since Groq validates tool-call arguments against the JSON schema *server-side*, demanding any single spelling turns that into a hard 400 that burns every retry and loses the whole recommendation. `Evidence` therefore makes `tool` optional on the wire and normalizes the aliases in a before-validator, while the Python attribute and serialized key stay `tool`.
- Malformed tool-call JSON (`tool_use_failed`) turned out to be *sticky*: resending the identical turn recovered 4 of 13 episodes on the second attempt and 1 of 9 on the third. The commonest case, reproduced live, is a zero-argument tool called with garbled empty arguments (`{"name": "price_history", "arguments": {""}"}`). `_invoke_with_retry` in `nodes/executor.py` now rebuilds such a call from Groq's `failed_generation` when it's unambiguous, retries otherwise with a note saying what was rejected, and only then degrades to a content-only message (setting `executor_degraded`), so the Synthesizer still produces a recommendation from the evidence already gathered.

### No optional numeric parameters on tools

`competitor_search()` and `price_history()` accept `max_results: int = 5` and `days: int = 90`. The LLM sometimes serialized these as strings (`"5"`), which then failed schema validation at Groq. Solution: the agent's per-ASIN closures don't expose them and pass the defaults themselves. The agent never needed to vary them; the MCP surface still offers them to external clients.

### `instructor` for structured outputs

LangChain has `with_structured_output()` but it's been spotty across model providers. `instructor.from_groq()` is provider-aware, supports retries on schema-validation failure, and produces real Pydantic objects (not dicts that *happen* to match a schema). Used in both the Planner and Synthesizer.

### `load_dotenv(override=True)` in eval scripts

Claude Code (the user's parent shell) exports its own `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` (pointing at its internal auth proxy). Eval scripts use `load_dotenv(override=True)` and `os.environ.pop('ANTHROPIC_BASE_URL', None)` so the user's own `console.anthropic.com` key takes precedence and the SDK hits the public API.

### Defensive `try/except` import inside `/agent/query`

`from backend.agent.graph import run_agent_streaming` is *inside* the FastAPI handler, not at module top-level. If a future change breaks the agent import path (missing dep, syntax error), the existing `/chat` and `/analyze` endpoints keep working — only `/agent/query` returns 503. Stability of v1 is non-negotiable.

### Frontend uses `fetch` + `ReadableStream`, not `EventSource`

`EventSource` is GET-only. We POST a body (`{asin, query}`) so we use `fetch` with `body.getReader()` and a tiny SSE frame parser. The format is still standard SSE; only the request shape differs.

---

## 8. Production migration path

Listed in the README's "What I'd do next" — repeating here with the migration steps spelled out for engineers evaluating the architecture.

### Scaling beyond 12 ASINs

**Cheap fix (~2 hours):** FAISS stores load lazily on first use. (`PRELOAD_CACHE=1` in [app.py](app.py) only warms the NLP/fusion cache for the 12 products at startup; it doesn't load FAISS.) For up to ~50 products, make that lazy path explicit per request:

```python
# In review_qa.py — instead of caching the chain at module init,
# build it on the first request for each ASIN and cache thereafter.
# Eviction policy: LRU with N=10 to bound memory.
```

This stays on Render's free tier and supports ~4x more products with no architecture change.

**Real scale (≥100 ASINs OR user-submitted products):** swap FAISS for a managed vector DB. The `review_qa` tool's external interface doesn't change — only the retrieval call underneath.

| Option | Best for | Free tier |
|---|---|---|
| Pinecone | Easiest start; serverless | 2GB |
| Qdrant Cloud | Open-source under the hood | Generous (~1GB) |
| pgvector on Supabase | If Postgres relational + vector storage are both useful | 500MB |

Plus an ingestion worker (Modal / Fly.io / Render background job) that:
1. Accepts a new ASIN from the UI
2. Fetches reviews (HuggingFace dataset → real Amazon API in production)
3. Runs sentiment + topic modeling
4. Embeds chunks
5. Upserts into the vector DB
6. Updates the supported-ASIN registry

This is a real project — a week or two of work — and worth doing *only* when there's user demand for it. Until then, the current architecture is appropriate.

### Multi-turn memory (shipped, without a checkpointer)

Follow-ups work today without server-side sessions. The browser sends the last three exchanges and, optionally, a pinned saved report; [backend/agent/context.py](backend/agent/context.py) renders them into one capped (2,400-char), deterministic block framed as background, not instructions or evidence. With no context, every prompt is byte-identical to a first question (`tests/test_context_golden.py`). A `langgraph` checkpointer (`SqliteSaver` with a `thread_id` per session) would only be needed for state the browser shouldn't hold.

### Self-critique loop (Critic node)

A new node between Synthesizer and END:

```
synthesizer → critic → END
                  └→ executor  (if quality < threshold)
```

Different from the existing low-confidence replan because the Critic evaluates *reasoning quality* (does the conclusion follow from the evidence?), not just the confidence number. Implementation: another `instructor` call with a `CriticVerdict` Pydantic model. Cap at 1 critic-triggered replan to bound iteration count.

### Fine-tuned planner

After logging 300+ real (`query`, `correct_plan`) pairs, the Planner's job — classify query + pick 2-4 tools from a fixed set of 6 — is small enough for SFT. A small open-weights model with LoRA on a few thousand examples should outperform the prompt-engineered planner on that step specifically, while staying cheap to serve.

The Executor and Synthesizer stay on the large model — they need general reasoning. Only the Planner gets specialized.

### Domain pivot — SEC filings

The architecture is domain-agnostic. To port to finance research:

1. New tool layer: `sec_filings_search`, `earnings_call_qa`, `price_fundamentals`, `analyst_trend_signal`.
2. New gold set: 30 questions of form "Should I add ${TICKER} to a thematic portfolio?" / "Why is ${TICKER}'s margin compressing?" / "How does ${TICKER} compare to peers?"
3. New evidence themes per query (analogous to the existing review_qa themes).

The Planner, Executor, Synthesizer prompts only need the *tool descriptions* updated. The graph structure, the eval harness, the SSE streaming, the frontend trace panel — all reusable as-is.

---

## File map for the curious

```
Repo root
├── app.py                                       # FastAPI: all endpoints (v1 + v2)
├── render.yaml                                  # Blueprint (the live Render service isn't managed by it)
├── requirements.txt                             # All runtime deps, agent layer included
├── requirements-agent.txt                       # Eval-only extras (deepeval, langsmith); not deployed
│
├── src/                          # v1 pipeline + shared config; agent tools wrap these
│   ├── ingest.py                 # 12 SUPPORTED_ASINS catalog
│   ├── nlp_pipeline.py           # Sentiment + topics
│   ├── fusion.py                 # XGBoost return-risk classifier + listing score
│   ├── llm_config.py             # Model chains, failover, timeouts
│   └── rag_chatbot.py            # FAISS RAG; ask_question() is the v1 → v2 reuse surface
│
├── backend/                      # v2
│   ├── agent/
│   │   ├── schemas.py            # Recommendation, Plan, AgentState
│   │   ├── prompts.py            # All system prompts in one file
│   │   ├── graph.py              # LangGraph state machine + run_agent + run_agent_streaming
│   │   ├── nodes/
│   │   │   ├── planner.py
│   │   │   ├── executor.py
│   │   │   └── synthesizer.py
│   │   ├── context.py            # Follow-up history / pinned report → one prompt block
│   │   ├── mock_stream.py        # Canned SSE fixture for /agent/query/mock
│   │   └── run.py                # CLI entry
│   ├── brief/                    # Executive Brief generator
│   ├── cache.py                  # Optional Redis SSE cache
│   ├── http_limits.py            # Per-IP rate limits, LLM budget, body cap
│   ├── internal_auth.py          # Shared-secret check for the Next.js proxy (dormant until set)
│   ├── mcp_server/
│   │   ├── server.py             # MCP stdio entry (mcp 2.x MCPServer)
│   │   └── tools/                # 6 tools — Python functions + MCP wrappers
│   └── data/mock_market_data.json
│
├── eval/
│   ├── gold_set.jsonl            # 39 queries (13 launch scored)
│   ├── run_eval.py               # Orchestrator
│   ├── judges.py                 # 4 DeepEval GEval metrics
│   ├── trajectory_eval.py        # F1 + ordering bonus
│   ├── baselines.py              # no_tool + single_tool
│   └── reports/                  # Generated Markdown + JSONL per run
│
├── frontend/
│   └── app/
│       ├── chat/         (v1)
│       ├── dashboard/    (v1 + Brief, Compare, Reports)
│       ├── assistant/    (v2, the live Copilot UI)
│       └── agent/        (v2, older mock-backed page)
│           ├── layout.tsx        # Sidebar + topbar shell
│           └── page.tsx          # Chat + TracePanel + Recommendation card
│
└── .github/workflows/
    ├── ci.yml                    # pytest + ruff gate + docker builds (required checks)
    └── eval-on-pr.yml            # 5-query keyed smoke eval on PRs
```
