# ListingLens Copilot — Agentic Seller Intelligence

> An AI agent for Amazon sellers. Plans research, calls the right tools, returns a structured recommendation with cited evidence.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-black?style=for-the-badge)](https://listinglens-kappa.vercel.app)
[![Python](https://img.shields.io/badge/Python-3.11-green?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js%2016-black?style=for-the-badge&logo=next.js)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/Agent-LangGraph%20v1-FF6F00?style=for-the-badge)](https://github.com/langchain-ai/langgraph)
[![MCP](https://img.shields.io/badge/Tools-MCP-7C3AED?style=for-the-badge)](https://modelcontextprotocol.io)
[![Groq](https://img.shields.io/badge/LLM-Groq%20Llama%204-orange?style=for-the-badge)](https://groq.com)

**[Live demo](https://listinglens-kappa.vercel.app/agent)** · **Loom walkthrough (90s):** *TBD — see [docs/LOOM_SCRIPT.md](docs/LOOM_SCRIPT.md)*

> ![Copilot demo — agent picks tools, streams a trace, returns a structured recommendation](docs/copilot-demo.gif)
> *Click a sample query → Planner picks the tools → Executor runs them → Synthesizer writes a Recommendation with cited evidence. Replace this GIF with your own screen recording at `docs/copilot-demo.gif`.*

---

## The problem this solves

Amazon sellers juggle Helium 10, Jungle Scout, Keepa, manual review scrolling, and gut feel when asking "Should I launch this variant?" or "Why are my returns spiking?". No single tool *reasons* across these signals. ListingLens Copilot does — it autonomously plans a research workflow, invokes the right tools, and returns a recommendation with cited evidence and a confidence score.

---

## What's new in v2: the Copilot

v1 (still live at [/dashboard](https://listinglens-kappa.vercel.app) and [/chat](https://listinglens-kappa.vercel.app/chat)) was a passive RAG: ask a question, retrieve from FAISS, LLM answers. Fixed steps, fixed order.

v2 ([/agent](https://listinglens-kappa.vercel.app/agent)) is an **active agent**. Given a seller question, it:

1. **Plans** — classifies the query type (launch / returns / improve) and picks a tool sequence
2. **Executes** — runs the planned tools, can re-plan if results surprise it
3. **Synthesizes** — produces a structured `Recommendation` with cited evidence

Five tools are wired into the agent:

| Tool | Purpose | Implementation |
|---|---|---|
| `review_qa` | Grounded Q&A over the product's reviews | **Reuses** the v1 FAISS RAG over real Amazon reviews |
| `predict_return_risk` | HIGH/MEDIUM/LOW return-risk score with drivers | **Reuses** the v1 XGBoost classifier |
| `competitor_search` | 3-5 competing products with prices, ratings, complaints | Mock data seeded for the 12 supported ASINs |
| `price_history` | 90-day price curve with volatility + events | Synthetic curve generated deterministically from a seed |
| `trend_signal` | 12-month category demand index + direction | Mock seeded per category |

Two of the five tools are powered by the **real** v1 models (FAISS RAG + XGBoost). Three are synthetic mocks at this stage — see [Stage 6 → "What I'd do next"](#what-id-do-next).

---

## Eval results — the credibility anchor

The whole project is graded by a 30-query gold set with LLM-as-judge (Claude Haiku 3, different model family from the Llama agent → no same-family bias) + trajectory F1. Full report at [eval/reports/2026-05-16-full.md](eval/reports/2026-05-16-full.md).

| Metric | Full agent | Notes |
|---|---|---|
| **Trajectory F1 (avg)** | **0.850** | Strongest signal — the Planner picks the right tools |
| Trajectory precision (avg) | 0.920 | Rarely calls a wrong tool |
| Trajectory recall (avg) | 0.824 | Occasionally misses one |
| First-tool match rate | 66.7% | Planner picks the right *starting* tool 2/3 of the time |
| **Decision accuracy** | **56.7%** | Agent's decision matches gold 17/30 — most failures are over-confidence on launch queries |
| Judge: anti-hallucination | 0.737 | Claims are mostly supported by cited evidence |
| Judge: completeness | 0.759 | Recommendations address all critical aspects |
| Latency p50 / p95 | 18.2s / 34.5s | Per-query end-to-end including LLM-as-judge |
| Error rate | 10.0% | 3/30 — all Groq daily-quota hits at end of run, not agent bugs |

**Reading these honestly:** Trajectory is the agent's strongest dimension — it consistently picks the right tools. Decision accuracy is moderate because the agent is over-confident on launch queries (predicts `go` where the gold says `needs_more_data` or `no_go`). The trajectory was correct in those cases; the agent saw the right evidence but committed too eagerly. The eval surfaces this systematically — that's exactly what it's for. Fixing the over-confidence is the next iteration of prompts, informed by this data.

Baselines (no-tool LLM, single-tool agent) are coming next — they ran into Groq's daily 500k-token cap during the first full eval. The eval harness is designed to run them as soon as the quota resets.

---

## Architecture

```
                ┌──────────────────────────────────┐
                │  Next.js 16 frontend (Vercel)    │
                │  ├─ /dashboard   (v1)            │
                │  ├─ /chat        (v1)            │
                │  └─ /agent       (v2 Copilot)    │
                │     ├─ ChatStream                │
                │     ├─ TracePanel (live SSE)     │
                │     └─ Recommendation card       │
                └─────────────┬────────────────────┘
                              │ SSE
                ┌─────────────▼────────────────────┐
                │  FastAPI backend (Render)        │
                │  ├─ POST /analyze   (v1)         │
                │  ├─ POST /chat      (v1)         │
                │  ├─ POST /agent/query     (NEW)  │
                │  └─ POST /agent/query/mock (NEW) │
                └─────────────┬────────────────────┘
                              │
                ┌─────────────▼────────────────────┐
                │  LangGraph v1 multi-node agent   │
                │  ┌──────────────────────────┐    │
                │  │  Planner  (instructor)   │    │
                │  └──────────┬───────────────┘    │
                │             ▼                    │
                │  ┌──────────────────────────┐    │
                │  │  Executor  ◄─┐           │    │
                │  │  + ToolNode  │ (loop ≤8) │    │
                │  └──────────┬───┴───────────┘    │
                │             ▼                    │
                │  ┌──────────────────────────┐    │
                │  │  Synthesizer (instructor)│    │
                │  └──┬───────────────────────┘    │
                │     │ if confidence < 0.5         │
                │     └──→ Executor (1 replan)     │
                └─────────────┬────────────────────┘
                              │ MCP (stdio)
                ┌─────────────▼────────────────────┐
                │  MCP Tool Server                 │
                │  ├─ review_qa         → FAISS RAG (real reviews)
                │  ├─ predict_return_risk → XGBoost (real model)
                │  ├─ competitor_search → mock seed
                │  ├─ price_history     → mock seed
                │  └─ trend_signal      → mock seed
                └──────────────────────────────────┘
```

Deep dive: **[ARCHITECTURE.md](ARCHITECTURE.md)** — state machine details, why each node exists, eval methodology.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Agent orchestration | LangGraph v1 | State-machine traceability; native ToolNode + checkpointer |
| Agent LLM | Groq Llama 4 Scout (`meta-llama/llama-4-scout-17b-16e-instruct`) | Fast, reliable JSON tool-calls. Llama 3.3 70B sometimes emits Llama-native `<function=...>` syntax that breaks Groq's parser |
| Tool protocol | MCP (Model Context Protocol) | Cross-vendor tool standard; tools are also importable Python functions for dev iteration |
| Structured output | Pydantic v2 + `instructor` | Type-safe Recommendation; no JSON parsing pain |
| Evaluation | DeepEval `GEval` + custom trajectory eval | LLM-as-judge primitives; trajectory F1 + ordering bonus on top |
| Judge LLM | Claude Haiku 3 (Anthropic) | Different family from agent (Llama) → no same-family bias |
| Tracing | LangSmith | Every node + tool call as a visual span |
| RAG (v1, reused) | FAISS + sentence-transformers `all-MiniLM-L6-v2` | 2,800+ chunks/product, on-disk, free |
| Return-risk (v1, reused) | XGBoost on engineered review features | 96.5% accuracy, 0.997 ROC-AUC on held-out data |
| Sentiment | HuggingFace Inference API — RoBERTa | Per-review compound score |
| Backend | FastAPI + Uvicorn (Render) | REST + SSE streaming |
| Frontend | Next.js 16 + Tailwind 4 + Radix (Vercel) | App Router with per-route layouts |
| Vector store | FAISS (on-disk) | See [What I'd do next](#what-id-do-next) for the scale-up migration path |

---

## Run it yourself

**Prerequisites:** Python 3.11+, Node.js 18+, `libomp` on macOS (`brew install libomp`).

```bash
git clone https://github.com/Het415/listinglens.git && cd listinglens

# Backend (existing /chat + new /agent)
uv venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-agent.txt
# Set GROQ_API_KEY, HUGGINGFACE_API_KEY in .env. Optional: ANTHROPIC_API_KEY (eval judge), LANGSMITH_API_KEY (tracing).
uvicorn app:app --reload --port 8000

# Frontend (in another terminal)
cd frontend && npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open `http://localhost:3000/agent` → pick an ASIN → click a sample query → watch the trace animate.

**Run the eval:**

```bash
# Full agent on 30 gold queries, with LLM-as-judge
python -m eval.run_eval

# Skip judges (no Anthropic key required)
python -m eval.run_eval --no-judge

# Smoke eval (5 queries) — what GitHub Actions runs on PRs
python -m eval.run_eval --limit 5
```

Reports written to `eval/reports/YYYY-MM-DD-{variant}.md` + `.jsonl`.

**Run the agent CLI** (skip the frontend):

```bash
python -m backend.agent.run --asin B08XPWDSWW "Why are returns spiking?" --pretty
```

---

## What I'd do next

The judgment section. These are deliberate omissions, not oversights — each one is worth doing *only* when there's a specific reason.

1. **Scale beyond 12 ASINs.** Current setup is FAISS-on-disk + all 12 vectorstores preloaded at startup ([app.py:31-64](app.py:31)). Fine for ≤50 products on the Render free tier. Cheap fix for more: lazy-load per request (~2 hours). Real scale (≥100 products or user-submitted ASINs): swap FAISS for a managed vector DB — Pinecone, Qdrant Cloud, or pgvector on Supabase. The `review_qa` tool's interface doesn't change; only retrieval underneath. **Don't migrate before there's a reason** — adding a managed DB doesn't make the agent smarter.

2. **Multi-turn memory.** Today is single-query → single-recommendation. Add LangGraph's SQLite checkpointer for conversation memory so the user can follow up ("OK and how does this change if I drop the price by 10%?") without re-running the full research path.

3. **Self-critique loop.** Add a Critic node between Synthesizer and END that evaluates *reasoning quality* (different from the existing confidence-based replan). On low quality, route back to Executor with explicit "expand on X" feedback.

4. **Fine-tuned planner.** After logging 300+ real queries with labels, fine-tune a small model (Llama 3.2 3B + LoRA) for just the planning step. The Planner is a smaller, more constrained task than full agency — a natural candidate for SFT.

5. **Domain pivot.** Same agent architecture, different tool layer: SEC filings + earnings transcripts + market data. One weekend to port. Same Planner/Executor/Synthesizer; only the tools change.

---

## How v1 (RAG + XGBoost) still works underneath

The v1 dashboard, chat, and analysis pages are untouched and continue to serve 12 pre-analyzed products. They power two of the five v2 agent tools (`review_qa` reuses the FAISS RAG, `predict_return_risk` reuses the XGBoost classifier). v2 extends v1; it doesn't replace it.

Key v1 implementation details (still relevant because they're part of the agent's tool layer):

- **Return-risk proxy labels** — real return-rate data isn't publicly available; the XGBoost model trains on a proxy combining `pct_negative`, `(1 - rating_avg/5)`, and `rating_sentiment_gap`. The third feature is the novel one: it catches products where customers write positive text but rate low — a leading indicator of returns before star ratings catch up. Performance on held-out data: 96.5% accuracy, 0.997 ROC-AUC. See [src/fusion.py](src/fusion.py).
- **RAG with metadata filter** — if the user's question mentions a star rating ("what do 1-star reviewers say"), retrieval applies a hard metadata filter to only those reviews before semantic search. Prevents the LLM from blending positive and negative content. See [src/rag_chatbot.py:123](src/rag_chatbot.py:123).
- **Star-balanced sampling** — sentiment is run on 250 reviews per product, balanced 50 per star rating, before scoring. Removes the bias from products with 90% five-star reviews drowning out real complaints. See [src/nlp_pipeline.py](src/nlp_pipeline.py).

---

## Supported products (12 pre-analyzed ASINs)

| ASIN | Product |
|---|---|
| B08XPWDSWW | TOZO T10 Bluetooth Earbuds |
| B07GZFM1ZM | Fire Stick 4K |
| B075X8471B | Fire TV Stick with Alexa |
| B01K8B8YA8 | Echo Dot 2nd Generation |
| B07H65KP63 | Echo Dot 3rd Generation |
| B0791TX5P5 | Fire TV Stick HD |
| B010BWYDYA | Fire Tablet 7 inch |
| B07S764D9V | Panasonic ErgoFit Wired Earbuds |
| B0BW4PFM58 | OontZ Angle 3 Bluetooth Speaker |
| B07PXGQC1Q | Apple AirPods 2nd Generation |
| B00N2ZDXW2 | Ring Video Doorbell |
| B08RLW7918 | WYZE Cam v2 Security Camera |

Pre-computing analysis for a new ASIN:

```bash
python precompute.py --asin B07XJ8C8F7
git add data/processed/ && git commit -m "add new product ASIN" && git push origin main
```

Render redeploys automatically.

---

## Project structure

```
listinglens/
├── app.py                            # FastAPI: /analyze, /chat, /agent/query, /agent/query/mock
├── src/                              # v1 RAG + ML pipeline (untouched)
│   ├── ingest.py
│   ├── nlp_pipeline.py
│   ├── fusion.py                     # XGBoost return-risk classifier
│   └── rag_chatbot.py                # FAISS RAG over reviews
├── backend/                          # v2 Copilot
│   ├── agent/
│   │   ├── graph.py                  # LangGraph state machine + streaming
│   │   ├── nodes/
│   │   │   ├── planner.py
│   │   │   ├── executor.py
│   │   │   └── synthesizer.py
│   │   ├── prompts.py
│   │   ├── schemas.py                # Pydantic Recommendation + AgentState
│   │   ├── mock_stream.py            # Canned SSE fixture for demos
│   │   └── run.py                    # CLI entry
│   ├── mcp_server/
│   │   ├── server.py                 # FastMCP stdio server
│   │   └── tools/                    # 5 tools as Python functions + MCP wrappers
│   └── data/mock_market_data.json    # Seed for competitor/price/trend tools
├── eval/                             # 30-query gold set + LLM-as-judge + trajectory F1
│   ├── gold_set.jsonl
│   ├── run_eval.py
│   ├── judges.py
│   ├── trajectory_eval.py
│   ├── baselines.py
│   └── reports/
├── frontend/
│   └── app/
│       ├── chat/                     # v1 chat UI
│       ├── dashboard/                # v1 dashboard
│       └── agent/                    # v2 Copilot UI
│           ├── layout.tsx
│           └── page.tsx
├── .github/workflows/eval-on-pr.yml  # 5-query smoke eval on PRs
└── ARCHITECTURE.md                   # Deep dive
```

---

## What I learned building this

**The eval IS the development loop.** I spent more time iterating on prompts after looking at the eval report than I did writing the original prompts. Without the gold set + LLM-as-judge + trajectory F1, "improving the agent" would have been vibes — "this answer feels better than before". With the eval, regressions and improvements are numbers.

**The trace panel is the unfair advantage.** Most agent demos show a final answer and you have to trust it. Showing the planner, the tool calls, the tool results, and the synthesizer in a live timeline does two things: it lets recruiters *see* the agent reasoning (which is the actual technical signal), and it gives me a real-time debugger when something goes wrong in dev.

**Honest evaluation beats inflated metrics.** The agent has a 56.7% decision accuracy. That's lower than what I'd see on a marketing slide. But the over-confidence pattern is *exactly* what a follow-up iteration of prompts will target, and the trajectory F1 of 0.85 says the planner is working. Hiring managers respond to honest numbers + a clear "what we'd fix next" story more than to suspiciously perfect ones.

---

## Author

**Het Prajapati** — MS Data Science, Northeastern University (May 2027)

[LinkedIn](https://linkedin.com/in/het-prajapati6210) · [GitHub](https://github.com/Het415) · [Live Demo](https://listinglens-kappa.vercel.app/agent)
