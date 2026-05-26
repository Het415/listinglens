# ListingLens Copilot

> An AI agent for Amazon sellers that plans its own research, calls the right tools, and returns a structured recommendation with cited evidence.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Online-black?style=for-the-badge)](https://listinglens.hetprajapati.me)
[![Python](https://img.shields.io/badge/Python-3.11-green?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js%2016-black?style=for-the-badge&logo=next.js)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/Agent-LangGraph%20v1-FF6F00?style=for-the-badge)](https://github.com/langchain-ai/langgraph)
[![Groq](https://img.shields.io/badge/LLM-Groq%20Llama%204-orange?style=for-the-badge)](https://groq.com)

![Copilot demo — agent picks tools, streams a trace, returns a structured recommendation](docs/copilot-demo.gif)

---

## What it does

Amazon sellers juggle Helium 10, Jungle Scout, Keepa, manual review scrolling, and gut feel when they ask things like *"Should I launch this variant?"* or *"Why are my returns spiking?"*. No single tool actually **reasons** across those signals.

ListingLens Copilot does. Ask it a question, and the agent:

1. **Plans** — figures out what kind of question it is and what data it needs
2. **Executes** — calls the right tools (review search, return-risk model, competitor lookup, price history, demand trends), re-planning if results surprise it
3. **Synthesizes** — produces a recommendation with cited evidence and a confidence score

The whole reasoning trace is visible live in the UI, so you can see *why* the agent reached its conclusion — not just *what* it concluded.

---

## Try it

**Live demo:** [listinglens.hetprajapati.me/agent](https://listinglens.hetprajapati.me/agent)

Pick any of the 12 pre-analyzed products (TOZO T10, Fire Stick 4K, AirPods, …), then try a sample query like:

- "Why are returns spiking?"
- "Should I launch this product?"
- "How does this compare to competitors?"

You'll see the planner pick tools, the executor run them with live results, and the synthesizer write a structured recommendation — all streaming in real time.

---

## Headline numbers

Evaluated on a 30-query benchmark, judged by Claude Haiku (different LLM family from the agent, so no same-family bias). Full report: [eval/reports/2026-05-16-full.md](eval/reports/2026-05-16-full.md).

| Metric | Score | What it means |
|---|---|---|
| **Tool-selection accuracy** | **0.85** | The planner picks the right tools the vast majority of the time |
| **Decision accuracy** | **57%** | Final recommendation matches the gold-set decision 17/30 times |
| Latency (p50 / p95) | 18s / 35s | End-to-end including the judge |
| Error rate | 10% | All 3 failures were Groq daily-quota hits, not agent bugs |

**Honest reading:** tool selection is the agent's strongest dimension. Decision accuracy is moderate because the agent over-commits on launch queries — it sees the right evidence but says "go" where the gold says "needs more data." That over-confidence is the next iteration's prompt target, surfaced systematically by the eval. The eval is the dev loop, not the scoreboard.

---

## How it works

```
                ┌──────────────────────────────────┐
                │  Next.js 16 frontend (Vercel)    │
                │  └─ /agent — live streaming UI   │
                └─────────────┬────────────────────┘
                              │ live event stream
                ┌─────────────▼────────────────────┐
                │  FastAPI backend (Render)        │
                │  POST /agent/query               │
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
                │      └──→ Executor (1 replan)    │
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

Two of the five tools are real:
- **`review_qa`** — semantic search over actual Amazon reviews using vector embeddings, then an LLM answers grounded in what it found
- **`predict_return_risk`** — an XGBoost classifier trained on engineered review features (96.5% accuracy on held-out data)

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

Open `http://localhost:3000/agent`.

### Option B: Python venv (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Frontend setup is identical to Option A.

### Run the eval

```bash
python -m eval.run_eval                    # full agent on 30 gold queries
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

**Agent layer:** [LangGraph](https://github.com/langchain-ai/langgraph) v1 as the state machine, [Groq](https://groq.com) running Llama 4 Scout for the LLM (fast, reliable structured output), [instructor](https://github.com/jxnl/instructor) + Pydantic v2 for type-safe outputs, [MCP](https://modelcontextprotocol.io) (Anthropic's tool protocol) as the tool interface.

**Real-data tools:** FAISS for vector search over ~2,800 review chunks per product, sentence-transformers `all-MiniLM-L6-v2` for embeddings, XGBoost for return-risk classification, HuggingFace's RoBERTa for sentiment.

**Eval:** custom trajectory-matching algorithm + DeepEval's `GEval` for LLM-as-judge scoring. Claude Haiku as judge (different family from Llama → no same-family bias). LangSmith for trace visualization.

**Infrastructure:** FastAPI + Uvicorn on Render (Python buildpack), Next.js 16 + Tailwind 4 + Radix on Vercel, Redis sidecar for caching expensive agent queries (840× speedup on repeats — see [docker-compose.yml](docker-compose.yml)).

**CI:** [GitHub Actions](.github/workflows/ci.yml) builds the backend + frontend Docker images and runs pytest on every PR. A separate workflow runs a 5-query smoke eval against the agent.

---

## What I'd build next

The judgment section — deliberate omissions, not oversights.

1. **Scale past 12 products.** Current setup preloads FAISS indexes at startup. Fine for ~50 products on the free tier; for ≥100, swap FAISS for a managed vector DB (Pinecone, Qdrant, or pgvector). The `review_qa` tool interface doesn't change — only what's underneath. Don't migrate before there's a reason.

2. **Multi-turn memory.** Today is single-query → single-recommendation. Adding LangGraph's SQLite checkpointer would let users follow up ("how does this change if I drop the price 10%?") without re-running the full research path.

3. **Self-critique loop.** A Critic node between Synthesizer and END that evaluates *reasoning quality* (different from the existing confidence-based replan). Routes back with explicit "expand on X" feedback when reasoning is thin.

4. **Fine-tuned planner.** After logging 300+ real queries with labels, fine-tune a small model (Llama 3.2 3B + LoRA) just for the planning step. Planning is a smaller, more constrained task than full agency — a natural candidate for supervised fine-tuning.

5. **Domain pivot.** Same architecture, different tools: SEC filings + earnings transcripts + market data. One weekend to port. The Planner/Executor/Synthesizer stay; only the tool layer changes.

---

## What I learned building this

**The eval IS the development loop.** I spent more time iterating prompts after reading eval reports than I did writing the original prompts. Without a gold set + judge + trajectory scoring, "improving the agent" would have been vibes. With it, regressions and improvements are numbers.

**The trace panel is the unfair advantage.** Most agent demos show a final answer and ask you to trust it. Showing the planner, the tools, the results, and the synthesizer in a live timeline lets people *see* the reasoning — and gives me a real-time debugger.

**Honest evaluation beats inflated metrics.** 57% decision accuracy is lower than what fits on a marketing slide. But the failure pattern (over-confidence on launch queries) is *exactly* what a follow-up iteration targets, and the 0.85 tool-selection score says the planner works. Hiring managers respond to honest numbers + a clear "what we'd fix next" story more than to suspiciously perfect ones.

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
├── eval/                   # 30-query gold set + judge + trajectory eval
├── frontend/app/agent/     # Next.js Copilot UI
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

[LinkedIn](https://linkedin.com/in/het-prajapati6210) · [GitHub](https://github.com/Het415) · [Live Demo](https://listinglens.hetprajapati.me/agent)
