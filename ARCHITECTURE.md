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
- **How:** a `ChatGroq` LLM with the 5 tools bound via `bind_tools(tools, parallel_tool_calls=False)`. The serial constraint is critical — see [Design tradeoffs](#7-design-tradeoffs-called-out).
- **Modes:** the system prompt has two paths — **normal** (follow the plan) and **re-plan** (Synthesizer asked for more evidence; pick unused tools).
- **Iteration cap:** state's `iterations` counter increments on every tool call. The routing edge after the executor sends it to Synthesizer if `iterations >= MAX_TOOL_ITERATIONS` (8).

#### `tools` (LangGraph prebuilt `ToolNode`)

Not really a "node" in the design sense — it's LangGraph's stock helper that takes the latest message's `tool_calls`, dispatches to the matching `@tool`-decorated function, and emits one `ToolMessage` per call. Zero custom code on our side.

#### Synthesizer — [backend/agent/nodes/synthesizer.py](backend/agent/nodes/synthesizer.py)

- **Job:** convert the trajectory (the full message history) into a structured `Recommendation`.
- **Input:** the full message log.
- **Output:** a `Recommendation` Pydantic object: `decision`, `confidence`, `summary`, `reasoning_steps`, `evidence`, `risks`, `suggested_next_actions`.
- **How:** `_build_transcript(...)` flattens the conversation into a compact text form (tool calls + tool results + executor thoughts), then one `instructor.from_groq` call with `response_model=Recommendation`.
- **Why a separate node instead of a final ReAct turn:** ReAct can emit unstructured prose. We want a typed, machine-validated payload that the frontend can render without parsing. `instructor` + Pydantic = no JSON-parsing errors at the API boundary.

#### `bump_replan` (pass-through)

Increments `replans_done` before re-entering the Executor. Explicit so the LangSmith trace shows when a re-plan happens — `if rec.confidence < 0.5 and replans_done < 1` triggers it. Capped at one extra loop to prevent infinite re-planning.

---

## 3. The tool layer (and the dual interface)

Five tools live in [backend/mcp_server/tools/](backend/mcp_server/tools/). Each is **two things at once**:

1. A **plain Python function** importable via `from backend.mcp_server.tools.review_qa import review_qa`. Used directly by the agent code, the eval harness, and unit tests. Fast iteration — no protocol overhead.
2. An **MCP-server tool** exposed over stdio by [backend/mcp_server/server.py](backend/mcp_server/server.py). Used when an external MCP client (Claude Desktop, Cursor) connects.

Same code, two surfaces. This avoids the trap of "the agent calls Python but the MCP server has a different implementation" — they share a single source of truth.

Per-tool surface:

| Tool | File | Inputs | Output | Underlying |
|---|---|---|---|---|
| `review_qa` | [review_qa.py](backend/mcp_server/tools/review_qa.py) | `asin: str, question: str` | `{answer, sources[], n_sources}` | v1's [`ask_question()`](src/rag_chatbot.py) over FAISS; chain cached per ASIN |
| `predict_return_risk` | [return_risk.py](backend/mcp_server/tools/return_risk.py) | `asin: str` | `{risk_score, risk_label, risk_pct, confidence, explanation}` | v1's [`run_fusion_pipeline()`](src/fusion.py) (XGBoost) |
| `competitor_search` | [competitor.py](backend/mcp_server/tools/competitor.py) | `asin: str` | `{category, n_results, competitors[]}` (each w/ title, brand, price, rating, top_complaints) | Seed data in `backend/data/mock_market_data.json` |
| `price_history` | [price.py](backend/mcp_server/tools/price.py) | `asin: str` | `{daily_prices[90], min/max/avg, volatility, key_events}` | Deterministic synthesis from seed (sinusoidal + event injection); same ASIN → same curve |
| `trend_signal` | [trends.py](backend/mcp_server/tools/trends.py) | `asin: str` (or `category`) | `{months[12], values[12], trend_direction, yoy_change_pct}` | Seed per category |

When the LangGraph agent binds tools, it wraps each MCP tool in a per-ASIN closure ([graph.py:_build_tools_for_asin](backend/agent/graph.py)). The closure has the ASIN baked in, so the LLM never has to supply it — it just passes the semantic arg (`question` for review_qa, no args for the others). That dropped a class of failure modes where the model would send `"max_results": "5"` (string) instead of `5` (int).

---

## 4. Evaluation methodology

Three independent axes, all reported. Full report at [eval/reports/2026-05-16-full.md](eval/reports/2026-05-16-full.md); methodology summary in [eval/README.md](eval/README.md).

### Axis 1: output quality (LLM-as-judge)

[eval/judges.py](eval/judges.py). Four DeepEval `GEval` metrics, each scoring 0.0-1.0:

| Metric | What it checks |
|---|---|
| `decision_correctness` | Does the agent's `decision` field match the gold `expected_decision`? 1.0 = exact match, 0.5 = directionally similar, 0.0 = confidently wrong |
| `evidence_relevance` | Do the cited evidence snippets cover the gold `expected_evidence_themes`? |
| `anti_hallucination` | Are the agent's claims supported by the cited tool outputs? (Higher = less hallucination) |
| `completeness` | Does the recommendation address all critical aspects: decision, reasoning, next actions, risks? |

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

Trajectory is *more diagnostic* than the final answer. If the agent called the wrong tools, the answer is wrong by accident even when it sounds plausible. The trajectory F1 of 0.85 (precision 0.92, recall 0.82) is the strongest claim the project makes about agent quality.

### Axis 3: operational metrics

In [eval/run_eval.py](eval/run_eval.py): per-query wall-clock latency, error rate, error types. Tokens/cost tracking is on the to-do list (the LangChain callback hooks need to be wired through).

### The gold set

[eval/gold_set.jsonl](eval/gold_set.jsonl). 30 hand-crafted queries:

- 10 per query type (launch / returns / improve)
- All 12 supported ASINs exercised (2-3 queries each)
- Decision distribution: 19 `go` / 9 `needs_more_data` / 2 `no_go` (the 2 no-go cases test the agent's ability to *actively decline*)
- Per-entry schema: `id`, `asin`, `product_name`, `query`, `query_type`, `expected_decision`, `expected_tools`, `expected_evidence_themes`, `notes`

Each query was authored such that the expected behavior is grounded in the actual NLP features cached in `data/processed/features_*.json`. For example, Ring Doorbell's "What's driving negative reviews?" gold expects evidence around customer service (44.8% negative in real data), setup, and connectivity — because the v1 NLP pipeline already surfaced those as the top complaint topics.

### Baselines (deferred)

[eval/baselines.py](eval/baselines.py) defines two:

- **`no_tool`** — single Groq LLM call, no tools available. The "minimum useful" floor.
- **`single_tool`** — agent with only `review_qa`. Shows the lift from adding the other four tools.

Both produce the same `AgentOutput` shape so the eval pipeline treats them uniformly. They weren't run in the first full eval because the agent's run used 498k of the Groq daily 500k TPD cap. They'll run after quota reset.

### CI eval

[.github/workflows/eval-on-pr.yml](.github/workflows/eval-on-pr.yml) runs a 5-query smoke eval on PRs (no judges — cost-free) and comments the report table in the PR.

---

## 5. SSE streaming + the trace panel

The new `POST /agent/query` endpoint in [app.py](app.py) returns a Server-Sent Events stream. Each agent phase emits an event the frontend can render in a live timeline.

**Backend side** — [backend/agent/graph.py:run_agent_streaming](backend/agent/graph.py) wraps `compiled.astream(stream_mode="updates")`. LangGraph yields `{node_name: state_delta}` after each node finishes. `_delta_to_events()` translates each delta into one or more frontend-friendly events:

| Event | Emitted from | Payload |
|---|---|---|
| `started` | top of run | `{asin, product_name, query}` |
| `node_started` | every node entry | `{node, label}` |
| `plan_ready` | planner | `{query_type, plan: [tool_names]}` |
| `tool_call` | executor | `{tool, args}` |
| `tool_result` | tools | `{tool, result_preview}` (truncated to 1200 chars) |
| `executor_thought` | executor | `{content}` |
| `node_completed` | every node exit | `{node}` |
| `replan` | bump_replan | `{reason}` |
| `recommendation` | synthesizer | full `Recommendation` JSON |
| `error` | exception in any node | `{message}` |
| `done` | normal stream end | `{}` |

**Frontend side** — [frontend/app/agent/page.tsx](frontend/app/agent/page.tsx) uses `fetch` + `ReadableStream` (not the browser's built-in `EventSource` because that's GET-only and we POST a query body). A small inline async iterator (`readSSE`) parses event frames and yields `{event, data}` pairs.

The `TracePanel` component renders one row per event with per-event icons (Lucide). The "currently in flight" loader spinner shows only on the **most recent event while the stream is still active** — once a newer event arrives or the stream ends, prior rows flip from spinner to checkmark. (This was an iteration after the first version had every node_started row spinning forever.)

**Mock endpoint** — there's also `POST /agent/query/mock` that streams a canned trace from [backend/agent/mock_stream.py](backend/agent/mock_stream.py) with realistic delays. Same SSE shape as the live endpoint. Used during frontend development to avoid burning Groq tokens, and as the default in production while Groq's daily quota is exhausted (toggle via `NEXT_PUBLIC_AGENT_LIVE` env var).

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

Failover triggers on exactly two conditions — model decommissioned (404 `model_not_found`) and rate-limited (429) — and on nothing else. A bad API key or a request *we* malformed propagates immediately rather than being retried against three models in a row and masking the real bug.

Verified by pinning **every** stage to the dead `llama-3.3-70b-versatile` / `llama-3.1-8b-instant`: the agent still returned a complete recommendation in 9.5s, logging each failover and pointing at `scripts/doctor.py`.

Only four free Groq models support both tool-calling and structured output — `gpt-oss-120b`, `gpt-oss-20b`, `gpt-oss-safeguard-20b`, `qwen3.8-27b`. `allam-2-7b`, `groq/compound` and `groq/compound-mini` reject a `tools` payload outright, so they cannot serve any stage here.

### Output-token limits are a separate, tighter cap

Groq enforces **output** tokens per minute (OTPM) separately from the input TPM cap, and rejects a request up front based on the output it *estimates* from `max_tokens` — not on what the model actually emits. `qwen3.8-27b` has OTPM=1000, so a RAG chain at `max_tokens=1024` claims the entire minute's budget and 429s before it runs. The RAG chain therefore caps at 512 (the prompt asks for "under 150 words" ≈ 200 tokens), and every client sets `request_timeout`, because langchain otherwise retries a 429 with backoff and no deadline — which hangs the uvicorn worker thread rather than returning an error.

### `reasoning_effort` per stage

The gpt-oss models are reasoning models: they emit a hidden reasoning trace before answering, billed against the completion budget. `reasoning_effort="low"` cut total tokens 280 → 171 on an identical prompt, and end-to-end agent latency from a 62.9s p50 to ~9s. Low for the planner, executor, RAG and intent stages; medium for the synthesizer and brief, where the output is the user-facing recommendation.

Two consequences worth knowing:

- **`max_tokens` must leave headroom for reasoning.** At `max_tokens=64` a tool-selection call spent the whole budget thinking and returned `finish_reason="length"` with no tool call at all. The executor runs at 2048 and the RAG chain at 1024 for this reason.
- **`.content` is empty on a pure tool-call turn**, with the rationale in `additional_kwargs["reasoning_content"]`. Anything rendering the Executor's thinking must read both — hence `thought_text()` in `src/llm_config.py`, used by the SSE trace in `graph.py` and the Synthesizer's transcript builder.

### `parallel_tool_calls=False`

Kept, but for a different reason than originally: the routing edge in `graph.py` assumes one tool call per turn, and the trace panel reads better serially. The graph already loops the Executor, so serial calling is functionally equivalent. (The original justification — keeping Llama models off their native XML function syntax — no longer applies.)

### Tolerant `Evidence.tool` and Executor retries

Two robustness measures that reasoning models made necessary:

- The gpt-oss models are inconsistent about the evidence field name. Across three retries of one query they emitted `tool_name`, `tool`, and `source`. Since Groq validates tool-call arguments against the JSON schema *server-side*, demanding any single spelling turns that into a hard 400 that burns every retry and loses the whole recommendation. `Evidence` therefore makes `tool` optional on the wire and normalizes the aliases in a before-validator, while the Python attribute and serialized key stay `tool`.
- Malformed tool-call JSON (`tool_use_failed`) is a stochastic generation slip — the same query succeeds on a retry. `_invoke_with_retry` in `nodes/executor.py` retries the turn up to three times, then degrades to a content-only message so the Synthesizer still produces a recommendation from the evidence already gathered, instead of failing the request.

### No optional numeric parameters on tools

`competitor_search()` and `price_history()` originally accepted `max_results: int = 5` and `days: int = 90`. The LLM sometimes serialized these as strings (`"5"`), which then failed schema validation at Groq. Solution: drop the optional params, hardcode the defaults inside the tool body. The agent never actually needed to vary them anyway.

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

**Cheap fix (~2 hours):** [app.py:31-64](app.py) can preload all 12 FAISS vectorstores into memory at startup via a background task, but this is opt-in and off by default (`PRELOAD_CACHE=0`), so stores load lazily on first use. For up to ~50 products, make that lazy path explicit per request:

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

### Multi-turn memory

Add `langgraph.checkpoint.sqlite.SqliteSaver`:

```python
from langgraph.checkpoint.sqlite import SqliteSaver

compiled = graph.compile(checkpointer=SqliteSaver.from_conn_string("checkpoints.db"))
```

Then run with a `thread_id` per user session. State automatically persists across `astream()` calls; follow-up questions don't restart the research path. Frontend would track `thread_id` in URL or sessionStorage.

### Self-critique loop (Critic node)

A new node between Synthesizer and END:

```
synthesizer → critic → END
                  └→ executor  (if quality < threshold)
```

Different from the existing low-confidence replan because the Critic evaluates *reasoning quality* (does the conclusion follow from the evidence?), not just the confidence number. Implementation: another `instructor` call with a `CriticVerdict` Pydantic model. Cap at 1 critic-triggered replan to bound iteration count.

### Fine-tuned planner

After logging 300+ real (`query`, `correct_plan`) pairs, the Planner's job — classify query + pick 2-4 tools from a fixed set of 5 — is small enough for SFT. A small open-weights model with LoRA on a few thousand examples should outperform the prompt-engineered planner on that step specifically, while staying cheap to serve.

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
├── render.yaml                                  # Deploy config; agent deps in requirements-agent.txt
├── requirements.txt + requirements-agent.txt    # Split so v2 deps don't bloat v1 deploys until needed
│
├── src/                          # v1 — untouched, agent tools wrap these
│   ├── ingest.py                 # 12 SUPPORTED_ASINS catalog
│   ├── nlp_pipeline.py           # Sentiment + topics
│   ├── fusion.py                 # XGBoost return-risk classifier
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
│   │   ├── mock_stream.py        # Canned SSE fixture for /agent/query/mock
│   │   └── run.py                # CLI entry
│   ├── mcp_server/
│   │   ├── server.py             # FastMCP stdio entry
│   │   └── tools/                # 5 tools — Python functions + MCP wrappers
│   └── data/mock_market_data.json
│
├── eval/
│   ├── gold_set.jsonl            # 30 queries
│   ├── run_eval.py               # Orchestrator
│   ├── judges.py                 # 4 DeepEval GEval metrics
│   ├── trajectory_eval.py        # F1 + ordering bonus
│   ├── baselines.py              # no_tool + single_tool
│   └── reports/                  # Generated Markdown + JSONL per run
│
├── frontend/
│   └── app/
│       ├── chat/         (v1)
│       ├── dashboard/    (v1)
│       └── agent/        (v2)
│           ├── layout.tsx        # Sidebar + topbar shell
│           └── page.tsx          # Chat + TracePanel + Recommendation card
│
└── .github/workflows/eval-on-pr.yml   # 5-query smoke eval on PRs
```
