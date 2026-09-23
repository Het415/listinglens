# ListingLens Copilot

> An AI agent for Amazon sellers that plans its own research, calls the right tools, and returns a structured recommendation with cited evidence.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Online-black?style=for-the-badge)](https://listinglens.hetprajapati.me)
[![Python](https://img.shields.io/badge/Python-3.13-green?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js%2016-black?style=for-the-badge&logo=next.js)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/Agent-LangGraph%20v1-FF6F00?style=for-the-badge)](https://github.com/langchain-ai/langgraph)
[![Groq](https://img.shields.io/badge/LLM-Groq%20gpt--oss-orange?style=for-the-badge)](https://groq.com)

![Copilot demo — agent picks tools, streams a trace, returns a structured recommendation](docs/copilot-demo.gif)

---

## What it does

Amazon sellers juggle Helium 10, Jungle Scout, Keepa, manual review scrolling, and gut feel when they ask things like *"Should I launch this variant?"* or *"Why are my returns spiking?"*. No single tool actually **reasons** across those signals.

ListingLens Copilot does. Ask it a question, and the agent:

1. **Plans** — figures out what kind of question it is and what data it needs
2. **Executes** — calls the right tools (review search, return-risk model, competitor lookup, price history, demand trends), re-planning if results surprise it
3. **Synthesizes** — produces a recommendation with cited evidence and a confidence score

The whole reasoning trace is visible live in the UI, so you can see *why* the agent reached its conclusion — not just *what* it concluded.

### Conversational customer-care analytics

Beyond single-turn reviews, ListingLens analyzes multi-turn **support conversations** — the same NLP that a contact-center / reservations team runs on call transcripts and chat logs:

- **Intent classification** — a scikit-learn model (TF-IDF word+char n-grams → LogisticRegression) trained on the real [Bitext](https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset) support dataset, with a Groq **LLM fallback** for low-confidence / out-of-distribution messages. Try it live on the Conversations page. Training report: [`eval/intent_report.md`](eval/intent_report.md).
- **Sentiment trajectory** — per-turn sentiment across a conversation, so you can see whether an interaction *recovered* (good service) or *escalated*.
- **Topic modeling** — embeddings-based (MiniLM → KMeans → c-TF-IDF), a model-based upgrade over keyword matching.
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

Evaluated on a 33-query benchmark, judged by Claude Haiku 4.5 (different LLM family from the agent, so no same-family bias). Full report: [eval/reports/2026-09-20-goldv2-judged.md](eval/reports/2026-09-20-goldv2-judged.md).

| Metric | Score | What it means |
|---|---|---|
| **Decision accuracy (launch only)** | **69.2%** | Against a 46.2% always-`needs_more_data` floor. Only launch is scored — see below |
| **Error rate** | **0.0%** | 33/33 completed; no errors and no degraded answers |
| Trajectory precision / F1 / recall | 0.849 / 0.798 / 0.811 | When the planner picks a tool it is usually one the gold set expects |
| Anti-hallucination (judge) | 0.824 | Claims are traceable to cited evidence |
| Completeness (judge) | 0.870 | Answers address what was asked |
| Evidence relevance (judge) | 0.548 | Weakest dimension — see below |
| Latency (p50 / p95) | 36s / 54s | End-to-end agent run, excluding the judge |
| `no_go` cases | 4/5 | Actively declining a bad idea, the hardest decision to get right |

**Honest reading — including the numbers that do not flatter the agent.** Every eval report now prints decision accuracy beside the baseline it has to beat, computed from the gold set at runtime rather than carried by hand. On the current 33-row set those floors are: a constant "always say `go`" predictor at **57.6%**, and a best-constant-per-query-type lookup at **69.7%**.

That comparison exposed a flaw in the benchmark itself, not just the agent. `go/no_go/needs_more_data` is *launch-decision* vocabulary — "Should I launch a wireless version?" has a real yes/no/unsure. But "Why are returns spiking?" has no proposal to approve, so `go` there just means "the agent answered", and 19 of the original 30 rows were `go`. A three-entry lookup table beat the agent. **Only `launch` now counts toward the headline**; returns and improve are reported as informational, and the all-types figure (66.7%) is still below its 69.7% lookup-table floor.

⚠️ **The scored number rose from 60% to 69.2%, and that is not the agent getting better.** The agent code was identical across both runs. What changed is the benchmark: adding three `no_go` cases dropped the launch floor from 60.0% to 46.2%, so the same behaviour now has room to show above a baseline instead of sitting exactly on it. The honest claim is that the measurement got sharper, not the model.

What is genuinely new evidence: the three added `no_go` cases were answered correctly **3/3 on first run**, at 0.85-0.86 confidence, each using the tools carrying the evidence — Amazon's own Lite already at the SKU's price, a competitor shipping Wi-Fi 6E whose top complaint is that nobody uses it, a category down 17.1% YoY. Declining a bad idea is the hardest of the three decisions, and it was previously unmeasurable at 2 rows.

The failure mode is **under-commitment, not over-confidence** — a correction to what this README previously claimed. Measured again on the 33-query set: 8 hedges (committal gold answered `needs_more_data`) against 2 over-commits. One launch row (`launch_007`) is still wrongly answered `go`, so the over-confidence the README used to describe is real but rare — it is now a single isolated case rather than the dominant pattern. The root cause is a contradiction in the synthesizer prompt: it is told to always populate `evidence_gaps`, *and* that a non-empty `evidence_gaps` forces `needs_more_data` — which makes `go` logically unreachable for launch queries. That is a fix with a known mechanism, not a tuning guess.

**And a caveat on reading any single run:** two runs of *identical* code flipped 11 of 24 comparable rows in opposite directions. This benchmark has a **~11-row (~37%) noise floor**, so a single-run delta smaller than that is meaningless. Detecting the prompt fix above needs repeated runs, or a narrower metric (per-type hedge-error count) as the primary signal. Knowing that a benchmark cannot resolve your change is more useful than a number that moves.

**Weakest dimension, and what it actually is.** `evidence_relevance` at 0.545 reads like a retrieval-ranking problem. It is not — the judge never once complains about ranking. The synthesizer truncates each tool result at 1500 characters while `review_qa`'s payload measures 2019–2218, so **3 of 5 retrieved review snippets are discarded before the synthesizer sees them**, on essentially every call. That is why answers stay thorough (completeness 0.870) while their citations go vague. Confirmed by the latest run: repairing four gold rows that demanded unreachable percentages left `evidence_relevance` flat at 0.548, because the truncation causing it is still there.

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
                │  5 Tools                         │
                │  • review_qa         (real RAG)  │
                │  • predict_return_risk (real ML) │
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

Two of the five tools run on real review data:
- **`review_qa`** — semantic search over actual Amazon reviews using vector embeddings, then an LLM answers grounded in what it found
- **`predict_return_risk`** — an XGBoost classifier over engineered review features (sentiment mix, the product's real average rating, a rating–sentiment gap). There is no return data behind it: it is trained on synthetic product profiles against a *proxy* label, a fixed threshold of three of its own inputs, so the score it reports is the probability of that proxy label, not a predicted return rate. Its held-out accuracy only measures how well it re-learns the threshold, so none is quoted here; the training record is `data/processed/xgboost_metrics.json`.

The other three (competitor, price, trend) are deterministic synthetic data — the agent doesn't know the difference, which means the architecture is real even where the data isn't yet. Wiring real market data in is a tool-layer swap, not an agent change.

For the deep dive — state machine, why each node exists, eval methodology — see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Run it yourself

### Option A: Docker (recommended)

```bash
git clone https://github.com/Het415/listinglens.git && cd listinglens
cp .env.example .env       # add GROQ_API_KEY and HUGGINGFACE_API_KEY
docker compose up --build
```

That's it. API on `http://localhost:8000`, Redis cache on `:6379`. First build is 5–10 min (downloading ~1.5 GB of ML wheels); subsequent rebuilds are seconds.

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
python -m eval.run_eval                    # full agent on all 33 gold queries
python -m eval.run_eval --no-judge         # skip LLM judging (no Anthropic key needed)
python -m eval.run_eval --limit 5          # 5-query smoke (what CI runs on PRs)
```

Reports land in `eval/reports/YYYY-MM-DD-{variant}.md`.

### Run the agent from the command line

```bash
python -m backend.agent.run --asin B08XPWDSWW "Why are returns spiking?" --pretty
```

---

## What's under the hood

**Agent layer:** [LangGraph](https://github.com/langchain-ai/langgraph) v1 as the state machine, [Groq](https://groq.com) running `gpt-oss-120b` for the planner/synthesizer and `gpt-oss-20b` for the executor loop, [instructor](https://github.com/jxnl/instructor) + Pydantic v2 for type-safe outputs, [MCP](https://modelcontextprotocol.io) (Anthropic's tool protocol) as the tool interface. Model IDs are centralized in [src/llm_config.py](src/llm_config.py), and each stage has an ordered **fallback chain** — Groq deprecates hosted models without notice, so a decommissioned or rate-limited model transparently fails over to the next live one instead of taking the app down. `python -m scripts.doctor` validates every pin and chain against Groq's live catalog.

**Degrading instead of dying.** Every node that calls an LLM can now lose its model chain without losing the run. `resilient_call` walks a stage's fallback chain on a 404 or 429, and retries the *same* model once on a malformed tool call — that one is stochastic, so a re-run usually fixes it. Caught live: the model emitted `"confidence": 0. nine` into an otherwise perfect payload, and one retry recovered it to a correct answer. When a chain is genuinely exhausted, the Synthesizer assembles a recommendation from the tool results already in state rather than raising, and the Executor hands off whatever evidence it gathered — both label the result as degraded so the UI never presents a placeholder verdict as a real one. Auth failures and malformed requests still fail loudly; masking those would turn an outage into a stream of plausible answers nobody investigates.

**Real-data tools:** FAISS for vector search over ~2,800 review chunks per product, `all-MiniLM-L6-v2` via ONNX Runtime for embeddings (local, CPU — no embedding API), XGBoost for return-risk classification, HuggingFace's RoBERTa for sentiment.

**Eval:** custom trajectory-matching algorithm + DeepEval's `GEval` for LLM-as-judge scoring. Claude Haiku as judge (different model family from the agent → no same-family bias). LangSmith for trace visualization.

**Infrastructure:** FastAPI + Uvicorn on Render (Python buildpack), Next.js 16 + Tailwind 4 + Radix on Vercel, Redis sidecar for caching expensive agent queries (840× speedup on repeats — see [docker-compose.yml](docker-compose.yml)).

**CI:** [GitHub Actions](.github/workflows/ci.yml) builds the backend + frontend Docker images and runs the 60-test pytest suite on every PR. A separate workflow runs a 5-query smoke eval against the agent. `python -m scripts.doctor` is the local preflight — it validates every model pin and fallback chain against Groq's live catalog, and `--probe` exercises the *real* `Recommendation` schema against each model rather than a toy one (a two-field stand-in passes everywhere and told us nothing).

---

## What I'd build next

The judgment section — deliberate omissions, not oversights. The first two are diagnosed down to the line, not guesses.

1. **Resolve the synthesizer prompt contradiction.** Always populate `evidence_gaps` + non-empty `evidence_gaps` forces `needs_more_data` = `go` is unreachable for launch queries. Fixing it has to be per-query-type: the hedging bias is *load-bearing* for launch, where gold is 6/10 `needs_more_data`, so a global de-hedge would trade 5 correct answers for 3. Verification needs repeated runs, per the noise floor above.

2. **Raise the 1500-char tool-result cap** in the synthesizer, which currently deletes 3 of 5 review snippets before they are ever seen. Measured cost of the fix: ~175 extra tokens per run, since `review_qa` is the only tool whose payload exceeds the cap.

3. **Scale past 12 products.** FAISS indexes are memory-mapped from disk on first use (eager preload is opt-in via `PRELOAD_CACHE=1`). Fine for ~50 products on the free tier; for ≥100, swap FAISS for a managed vector DB (Pinecone, Qdrant, or pgvector). The `review_qa` tool interface doesn't change — only what's underneath. Don't migrate before there's a reason.

4. **Multi-turn memory.** Today is single-query → single-recommendation. Adding LangGraph's SQLite checkpointer would let users follow up ("how does this change if I drop the price 10%?") without re-running the full research path.

5. **Self-critique loop.** A Critic node between Synthesizer and END that evaluates *reasoning quality* (different from the existing confidence-based replan). Routes back with explicit "expand on X" feedback when reasoning is thin.

6. **Fine-tuned planner.** After logging 300+ real queries with labels, fine-tune a small open-weights model with LoRA just for the planning step. Planning is a smaller, more constrained task than full agency — a natural candidate for supervised fine-tuning.

7. **Domain pivot.** Same architecture, different tools: SEC filings + earnings transcripts + market data. One weekend to port. The Planner/Executor/Synthesizer stay; only the tool layer changes.

---

## What I learned building this

**The eval IS the development loop.** I spent more time iterating prompts after reading eval reports than I did writing the original prompts. Without a gold set + judge + trajectory scoring, "improving the agent" would have been vibes. With it, regressions and improvements are numbers.

**The trace panel is the unfair advantage.** Most agent demos show a final answer and ask you to trust it. Showing the planner, the tools, the results, and the synthesizer in a live timeline lets people *see* the reasoning — and gives me a real-time debugger.

**Honest evaluation beats inflated metrics.** 60% decision accuracy is lower than what fits on a marketing slide, and a constant "always say go" baseline beats it. Publishing that is the point: it says precisely where the agent's value is (trajectory precision 0.865, anti-hallucination 0.811) and where it is not yet.

**I was wrong about my own agent, and the data said so.** This README used to claim the failure mode was over-confidence on launch queries. Measuring it properly showed the opposite — 8 hedges against 3 over-commits, and zero wrong `go`s on launch. A fix had already landed months earlier and overshot, and the stale diagnosis survived because nobody re-derived it. Acting on the old story would have made the agent worse.

**Know what your benchmark cannot see.** Two runs of identical code disagreed on 11 of 24 rows. Any single-run improvement smaller than that is noise, which means the honest next step is a repeated-runs design, not another prompt tweak measured once. A benchmark you trust past its resolution is worse than no benchmark.

---

## Project structure (brief)

```
listinglens/
├── app.py                  # FastAPI entrypoint
├── src/                    # v1 RAG + ML pipeline (used by agent tools)
├── backend/
│   ├── agent/              # LangGraph state machine + nodes
│   ├── mcp_server/tools/   # 5 tools as Python functions + MCP wrappers
│   └── cache.py            # Redis-backed SSE cache
├── eval/                   # 33-query gold set + judge + trajectory eval
├── frontend/app/assistant/ # Next.js Copilot UI (live; /agent is a mock fixture)
├── Dockerfile              # Backend image
├── docker-compose.yml      # api + redis sidecar
└── .github/workflows/      # CI: pytest + docker build + smoke eval
```

Add a new pre-analyzed product:

```bash
python precompute.py --asin B07XJ8C8F7
git add data/processed/ && git commit -m "add new ASIN" && git push
```

Render auto-redeploys.

---

## Author

**Het Prajapati** — MS Data Science, Northeastern University (May 2027)

[LinkedIn](https://linkedin.com/in/het-prajapati6210) · [GitHub](https://github.com/Het415) · [Live Demo](https://listinglens.hetprajapati.me/assistant)
