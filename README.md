# ListingLens Copilot

> An AI agent for Amazon sellers that plans its own research, calls the right tools, and returns a structured recommendation with cited evidence.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Online-black?style=for-the-badge)](https://listinglens.hetprajapati.me)
[![Python](https://img.shields.io/badge/Python-3.13-green?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js%2016-black?style=for-the-badge&logo=next.js)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/Agent-LangGraph%20v1-FF6F00?style=for-the-badge)](https://github.com/langchain-ai/langgraph)
[![Groq](https://img.shields.io/badge/LLM-Groq%20gpt--oss-orange?style=for-the-badge)](https://groq.com)

---

## What it does

Amazon sellers juggle Helium 10, Jungle Scout, Keepa, manual review scrolling, and gut feel when they ask things like *"Should I launch this variant?"* or *"Why are my returns spiking?"*. No single tool actually **reasons** across those signals.

ListingLens Copilot does. Ask it a question, and the agent:

1. **Plans** — figures out what kind of question it is and what data it needs
2. **Executes** — calls the right tools (review search, return-risk model, competitor lookup, price history, demand trends), re-planning if results surprise it
3. **Synthesizes** — produces a recommendation with cited evidence and a confidence score

The whole reasoning trace is visible live in the UI, so you can see *why* the agent reached its conclusion — not just *what* it concluded. Follow-up questions carry the last three exchanges, and a saved report can be pinned to continue the conversation from it.

### Conversational customer-care analytics

Beyond single-turn reviews, ListingLens analyzes multi-turn **support conversations** — the same NLP that a contact-center / reservations team runs on call transcripts and chat logs. The conversations themselves are **synthetic**: an LLM generated them from seeded intents, so their KPIs (resolution, escalation, sentiment recovery) describe the generator, not real customers.

- **Intent classification** — a scikit-learn model (TF-IDF word+char n-grams → LogisticRegression) trained on the real [Bitext](https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset) support dataset, with a Groq **LLM fallback** for low-confidence / out-of-distribution messages. Try it live on the Conversations page. Training report: [`eval/intent_report.md`](eval/intent_report.md). **Known gap:** the dashboard's precomputed intents are classified without the LLM fallback, and they agree with the generator's seeded intents only 18% of the time, which is what always guessing the most common intent scores. The Bitext-trained model doesn't transfer to these conversations yet.
- **Sentiment trajectory** — per-turn sentiment across a conversation, so you can see whether an interaction *recovered* (good service) or *escalated*.
- **Topic modeling** — embeddings-based (MiniLM → KMeans → c-TF-IDF) over the conversation openers. Review topics on the dashboard use keyword categories matched as whole words.
- **Executive Brief** — an LLM-synthesized, exec-ready one-pager that fuses review signals + return risk + conversation analytics into quantified findings and prioritized actions, exportable to PDF.

All of it is queryable as **SQL** via an embedded **DuckDB** warehouse (`scripts/build_duckdb.py`); see [`notebooks/eda.ipynb`](notebooks/eda.ipynb) and [`docs/sql_examples.sql`](docs/sql_examples.sql).

---

## Try it

**Live demo:** [listinglens.hetprajapati.me/assistant](https://listinglens.hetprajapati.me/assistant)

Pick any of the 12 pre-analyzed products (TOZO T10, Fire Stick 4K, AirPods, …), then try a sample query like:

- "Why are returns spiking?"
- "Should I launch this product?"
- "How does this compare to competitors?"

You'll see the planner pick tools, the executor run them with live results, and the synthesizer write a structured recommendation — all streaming in real time.

---

## Headline numbers

The headline is a repeated-runs evaluation of the agent's **launch decisions**, the one question type where `go` / `no_go` / `needs_more_data` is a real call. It ran 2026-09-23 → 10-01 on code frozen at `b1eb690d`, over the 13 `launch` rows of [eval/gold_set.jsonl](eval/gold_set.jsonl) (6 `needs_more_data`, 5 `no_go`, 2 `go`), with no LLM judge. The keep/discard rule for each run was written down before it ran.

| | Runs | Launch decision accuracy | 95% interval (Wilson) |
|---|---|---|---|
| **Full agent** (6 tools) | 2 | **5/13 = 38.5%** right in both runs (7/13 and 6/13 per run) | 17.7–64.5% |
| No-tool baseline (same LLM, no tools) | 3 | 6/13 = 46.2% (6/13 every run) | 23.2–70.9% |
| Constant floor (always `needs_more_data`) | — | 6/13 = 46.2% | 23.2–70.9% |

Paired on the same rows: the agent alone was right on 1, the baseline alone on 2, exact McNemar p = 1.0. In the agent's two kept runs: 0 errored and 0 degraded rows, trajectory F1 0.83 / 0.82, latency p50 47 s / 42 s and p95 101 s / 67 s (free-tier rate limits make most of the tail).

**Reading: no measurable lift on launch decisions.** With 13 rows the intervals overlap almost completely. So this doesn't show the agent is worse; it shows the benchmark can't tell it apart from always answering `needs_more_data`, which is what the no-tool baseline did on all 39 of its answers. Two runs of identical code also agreed on only 9 of 13 rows, so a single-run difference of a few rows is noise.

**Why the agent hedges.** Diagnosed, not guessed:
1. **The synthesizer prompt makes `go` nearly unreachable on launch questions.** It requires `evidence_gaps` on every answer, even a `go`, and says a non-empty `evidence_gaps` forces `needs_more_data` ([backend/agent/prompts.py](backend/agent/prompts.py)).
2. **The executor often stopped before the review search.** `review_qa` ran on 8/13 and 4/13 rows in the two kept runs. But when an experimental prompt made the executor finish every plan (`review_qa` on 13/13 rows), 7/13 answers were still `needs_more_data`, which points back at (1).

**What the old 69.2% was.** This README used to headline 69.2% launch accuracy from a 2026-09-20 run. Three of its 13 launch rows were also the synthesizer's few-shot examples, quoted with their gold answers: test-set leakage, removed in `2ffa1f05`. That run also recorded no commit, so it couldn't be reproduced. Don't quote it.

**How the measurement works now:**
- Every report stamps the git commit (and whether the tree was dirty), the gold set's sha256 and the prompts' sha256.
- A degraded run (a stage gave up and the answer was assembled without the model) is flagged and never scored as correct. The CI smoke eval fails on any errored or degraded row.
- LLM-as-judge scores aren't in the headline. The evidence-relevance judge is shown the expected decision, and the grounding judge never sees the raw tool outputs, so neither measures what its name says.

**A gate that did its job.** A change that made the executor prompt cacheable (14–21% of prompt tokens served from Groq's cache) had to pass a pre-registered paired eval before it could merge. It didn't: degraded runs rose from 3 of 65 rows to 16 of 52 (one-sided Fisher p = 0.0001), so it was shelved. Tracing those failures found the model garbling calls to tools that take no arguments, e.g. `{"name": "price_history", "arguments": {""}"}`. The executor now rebuilds such a call instead of resending the same request (PR #19).

The eval is the dev loop, not the scoreboard.

---

## How it works

```
                ┌──────────────────────────────────┐
                │  Next.js 16 frontend (Vercel)    │
                │  └─ /assistant — streaming UI    │
                └─────────────┬────────────────────┘
                              │ live event stream (SSE)
                ┌─────────────▼────────────────────┐
                │  FastAPI backend (Render)        │
                │  POST /assistant/query           │
                └─────────────┬────────────────────┘
                              │
                ┌─────────────▼────────────────────┐
                │  LangGraph agent                 │
                │   ┌──────────────────────────┐   │
                │   │  Planner                 │   │
                │   └──────────┬───────────────┘   │
                │              ▼                   │
                │   ┌──────────────────────────┐   │
                │   │  Executor  ◄─┐           │   │
                │   │  + Tools     │ (loop ≤8) │   │
                │   └──────────┬───┴───────────┘   │
                │              ▼                   │
                │   ┌──────────────────────────┐   │
                │   │  Synthesizer             │   │
                │   └──┬───────────────────────┘   │
                │      │ if confidence < 0.5       │
                │      └──→ Executor (1 replan)*   │
                └─────────────┬────────────────────┘
                              │
                ┌─────────────▼────────────────────┐
                │  6 Tools                         │
                │  • review_qa         (real RAG)  │
                │  • predict_return_risk (real ML) │
                │  • image_audit    (rule checks)  │
                │  • competitor_search (synthetic) │
                │  • price_history     (synthetic) │
                │  • trend_signal      (synthetic) │
                └──────────────────────────────────┘
```

\* The replan edge is wired but has **never fired in practice** — the lowest confidence
observed across 76 logged runs is 0.52, just above the 0.5 threshold, because the
synthesizer prompt's worked examples anchor hedged answers at 0.55. Recorded here rather
than quietly listed as a feature; re-arming it means gating on missing tools instead of
on self-reported confidence.

Two of the six tools run on real review data:
- **`review_qa`** — semantic search over actual Amazon reviews using vector embeddings, then an LLM answers grounded in what it found
- **`predict_return_risk`** — an XGBoost classifier over engineered review features (sentiment mix, the product's real average rating, a rating–sentiment gap). There is no return data behind it: it is trained on synthetic product profiles against a *proxy* label, a fixed threshold of three of its own inputs, so the score it reports is the probability of that proxy label, not a predicted return rate. Its held-out accuracy only measures how well it re-learns the threshold, so none is quoted here; the training record is `data/processed/xgboost_metrics.json`.
  - **It scores all 12 catalog products LOW, and that is not a bug.** Since the 2026-09-23 fixes (real average ratings, and sentiment weighted to each product's real star mix), every product scores 0.0–0.4%. That is what its own label definition says: the proxy score, 0.4 × negative share + 0.4 × (1 − rating/5) + 0.2 × rating–sentiment gap, is 0.09–0.17 for these 4.1–4.6★ products, against a 0.30 cut. A catalog of well-rated products is low-risk by the definition the model learns. The old HIGH scores came from reading every product as 3.0★.
  - The dashboard's **Overall Listing Score** scales that same composite (0 → 100, the 0.30 risk line → 50), so it reads 72–86 instead of showing 100 for every product, which is what the model's near-zero probability gave.

`image_audit` checks a listing's uploaded images against Amazon's published main-image rules: deterministic verdicts from a separate vision service, not a model judgement. The other three (competitor, price, trend) are deterministic synthetic data — the agent doesn't know the difference, which means the architecture is real even where the data isn't yet. Wiring real market data in is a tool-layer swap, not an agent change.

For the deep dive — state machine, why each node exists, eval methodology — see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Run it yourself

### Option A: Docker (recommended)

```bash
git clone https://github.com/Het415/listinglens.git && cd listinglens
cp .env.example .env       # add GROQ_API_KEY and HUGGINGFACE_API_KEY
docker compose up --build
```

That's it. API on `http://localhost:8000`, Redis cache on `:6379`. First build is 5–10 min (about 600 MB of ML wheels); subsequent rebuilds are seconds.

Then in another terminal, run the frontend:

```bash
cd frontend && npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open `http://localhost:3000/assistant`. (`/agent` also exists but defaults to a canned mock fixture — set `NEXT_PUBLIC_AGENT_LIVE=true` to point it at the live endpoint.)

### Option B: Python venv (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Frontend setup is identical to Option A.

### Check the stack before running anything LLM-shaped

```bash
python -m scripts.doctor            # model pins + fallback chains vs Groq's live catalog
python -m scripts.doctor --probe    # ...plus one real call per model on the actual schema
scripts/predemo_check.sh            # backend latency, demo-ASIN warmth, live-vs-local commit
```

### Run the eval

```bash
python -m eval.run_eval                    # full agent on all 39 gold queries (only launch rows are scored)
python -m eval.run_eval --no-judge         # skip LLM judging (no Anthropic key needed)
python -m eval.run_eval --limit 5          # 5-query stratified smoke (what CI runs on PRs)
python -m eval.run_eval --baseline no_tool # the same questions answered with no tools
```

Reports land in `eval/reports/YYYY-MM-DD-{variant}.md`. The headline series passed the 13 `launch` rows of the gold set as its `--gold` file.

### Run the agent from the command line

```bash
python -m backend.agent.run --asin B08XPWDSWW "Why are returns spiking?" --pretty
```

---

## What's under the hood

**Agent layer:** [LangGraph](https://github.com/langchain-ai/langgraph) v1 as the state machine, [Groq](https://groq.com) running `gpt-oss-120b` for the planner/synthesizer and `gpt-oss-20b` for the executor loop, [instructor](https://github.com/jxnl/instructor) + Pydantic v2 for type-safe outputs. The agent calls its tools as plain Python functions; the same six are also served over [MCP](https://modelcontextprotocol.io) by `python -m backend.mcp_server.server`. Model IDs are centralized in [src/llm_config.py](src/llm_config.py), and each stage has an ordered **fallback chain** — Groq deprecates hosted models without notice, so a decommissioned or rate-limited model transparently fails over to the next live one instead of taking the app down. `python -m scripts.doctor` validates every pin and chain against Groq's live catalog.

**Degrading instead of dying.** Every node that calls an LLM can lose its model chain without losing the run. `resilient_call` walks a stage's fallback chain on a 404, a 429, a timeout, a dropped connection or a 5xx, and stops trying slow providers once a stage has spent 45 s. Malformed tool calls turned out to be *sticky* (resending the identical turn recovered 1 of 9 on a third try), so the executor first rebuilds a call it can read unambiguously from the rejected generation, then retries with a note saying what was rejected. When a chain is genuinely exhausted, the Synthesizer assembles a recommendation from the tool results already in state rather than raising, and the Executor hands off whatever evidence it gathered. Both label the result as degraded, so the UI never presents a placeholder verdict as a real one. Auth failures and malformed requests still fail loudly; masking those would turn an outage into a stream of plausible answers nobody investigates.

**Real-data tools:** FAISS for vector search over about 3,000 review chunks per product, `all-MiniLM-L6-v2` via ONNX Runtime for embeddings (local, CPU — no embedding API), XGBoost for return-risk classification, HuggingFace's RoBERTa for sentiment.

**Eval:** decision accuracy against runtime baselines, a custom trajectory-matching score, Wilson intervals and exact McNemar tests across repeated runs. DeepEval's `GEval` judges (Claude Haiku) exist but stay out of the headline until they stop seeing the expected answer. LangSmith for trace visualization.

**Infrastructure:** FastAPI + Uvicorn on Render (Python buildpack), Next.js 16 + Tailwind 4 + Radix on Vercel, Google and GitHub sign-in (Better Auth) with saved reports and chats in Neon Postgres. Every LLM route is rate-limited per client IP, with a daily LLM budget and a request-body cap. Redis caching of repeated agent queries is optional: it runs in [docker-compose.yml](docker-compose.yml), not in production.

**CI:** [GitHub Actions](.github/workflows/ci.yml) builds the backend + frontend Docker images, runs the pytest suite (550+ tests) and a ruff lint gate on every PR; branch protection requires both checks before a PR can merge into `main`. A separate keyed workflow runs a 5-query smoke eval of the live agent on PRs that touch its code, and fails on any errored or degraded row. `python -m scripts.doctor` is the local preflight — it validates every model pin and fallback chain against Groq's live catalog, and `--probe` exercises the *real* `Recommendation` schema against each model rather than a toy one (a two-field stand-in passes everywhere and told us nothing).

---

## What I'd build next

The judgment section — deliberate omissions, not oversights. The first two are diagnosed down to the line, not guesses.

1. **Resolve the synthesizer prompt contradiction.** Always populating `evidence_gaps`, plus "non-empty `evidence_gaps` forces `needs_more_data`", makes `go` nearly unreachable for launch queries (1–3 launch `go`s per run). Fixing it has to be per-query-type: the hedging bias is *load-bearing* for launch, where gold is 6/13 `needs_more_data`, so a global de-hedge could trade correct hedges for wrong commitments. Verifying it needs the same repeated-runs design as the headline.

2. **Fix the judges, then measure evidence quality.** The evidence-relevance judge is handed the expected decision, and the grounding judge never sees the raw tool outputs. Until both are fixed, judge scores measure agreement with the gold answer, not the quality of the evidence.

3. **Survive free-tier rate limits.** Groq's free tier allows 8,000 tokens per minute per model, and a single agent run's executor can use more. Waiting out a short limit instead of failing over to a weaker model would cut most degraded runs.

4. **Scale past 12 products.** FAISS indexes are loaded from disk on first use. Fine for ~50 products on the free tier; for ≥100, swap FAISS for a managed vector DB (Pinecone, Qdrant, or pgvector). The `review_qa` tool interface doesn't change — only what's underneath. Adding a product isn't automated yet: `precompute.py` doesn't take an ASIN, and no script rebuilds the FAISS index.

5. **Self-critique loop.** A Critic node between Synthesizer and END that evaluates *reasoning quality* (different from the existing confidence-based replan). Routes back with explicit "expand on X" feedback when reasoning is thin.

6. **Fine-tuned planner.** After logging 300+ real queries with labels, fine-tune a small open-weights model with LoRA just for the planning step. Planning is a smaller, more constrained task than full agency — a natural candidate for supervised fine-tuning.

7. **Domain pivot.** Same architecture, different tools: SEC filings + earnings transcripts + market data. The Planner/Executor/Synthesizer stay; only the tool layer changes.

---

## What I learned building this

**The eval IS the development loop.** I spent more time iterating prompts after reading eval reports than I did writing the original prompts. Without a gold set + judge + trajectory scoring, "improving the agent" would have been vibes. With it, regressions and improvements are numbers.

**The trace panel is the unfair advantage.** Most agent demos show a final answer and ask you to trust it. Showing the planner, the tools, the results, and the synthesizer in a live timeline lets people *see* the reasoning — and gives me a real-time debugger.

**The most useful result was a null one.** Once the leakage was gone and every run was stamped and repeated, the agent's launch accuracy (5/13) couldn't be told apart from always saying `needs_more_data` (6/13). That's lower than anything that fits on a slide, and it's precise: it points at one rule in the synthesizer prompt instead of at "more prompt tuning".

**I was wrong about my own agent, and the data said so.** This README used to claim the failure mode was over-confidence on launch queries. Measuring it properly showed the opposite: the agent hedges far more than it over-commits. A fix had already landed months earlier and overshot, and the stale diagnosis survived because nobody re-derived it. Acting on the old story would have made the agent worse.

**Know what your benchmark cannot see.** Two runs of truly identical code disagreed on 4 of 13 launch rows. Any single-run improvement smaller than that is noise, which is why the headline is a repeated-runs design with intervals, not one run. A benchmark you trust past its resolution is worse than no benchmark.

**Write the rule down before the run.** Each pass's keep/discard rule, and the merge gate for the prompt-cache change, was fixed before any result came in. When that change failed its gate, the failure was a finding (the model garbling empty tool calls), not something to argue away.

---

## Project structure (brief)

```
listinglens/
├── app.py                  # FastAPI entrypoint
├── src/                    # v1 RAG + ML pipeline (used by agent tools)
├── backend/
│   ├── agent/              # LangGraph state machine + nodes
│   ├── mcp_server/tools/   # 6 tools as Python functions + an MCP server
│   └── cache.py            # Redis-backed SSE cache
├── eval/                   # 39-query gold set, baselines, trajectory eval, reports
├── frontend/app/assistant/ # Next.js Copilot UI (live; /agent is a mock fixture)
├── Dockerfile              # Backend image
├── docker-compose.yml      # api + redis sidecar
└── .github/workflows/      # CI: pytest + docker build + smoke eval
```

---

## Author

**Het Prajapati** — MS Data Science, Northeastern University (May 2027)

[LinkedIn](https://linkedin.com/in/het-prajapati6210) · [GitHub](https://github.com/Het415) · [Live Demo](https://listinglens.hetprajapati.me/assistant)
