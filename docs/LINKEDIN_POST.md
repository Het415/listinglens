# LinkedIn Post — ListingLens Copilot Launch

Three options below — pick whichever tone feels most like you. None of them say "leveraging" or "robust". Add the demo GIF + eval table screenshot before posting.

---

## Option A — Lead with the eval (recommended for AI/ML roles)

> Built an AI agent that helps Amazon sellers decide things like "Should I launch this variant?" or "Why are my returns spiking?"
>
> The interesting part isn't the agent — it's the evaluation harness.
>
> 30 hand-crafted gold queries. LLM-as-judge using Claude (different model family than the Llama agent to avoid same-family bias). Plus trajectory F1 — does the agent call the *right* tools in the *right* order.
>
> Results:
> · Trajectory F1: 0.85 (precision 0.92, recall 0.82)
> · Decision accuracy: 57% — agent is over-confident on launch queries, which the eval surfaces honestly
> · Latency p50/p95: 18s / 35s
>
> Most agent demos show a final answer and you have to trust it. The eval IS the development loop. Without it, "improving the agent" is vibes.
>
> Stack: LangGraph v1 (state machine), MCP (tool protocol), instructor + Pydantic (structured output), Groq Llama 4 Scout (agent), Anthropic Claude Haiku (judge).
>
> Live demo + full source + eval methodology: <links>
>
> 90-second walkthrough: <Loom link>
>
> #LangGraph #LLMOps #AgenticAI #MachineLearning

---

## Option B — Lead with the demo (recommended for SWE roles)

> v1 of this was a passive RAG: ask a question, retrieve, answer. v2 is an active agent that plans its own research.
>
> Given a seller question, it:
> 1. Picks 2-4 tools to call (out of 5 available)
> 2. Executes them, can re-plan if results surprise it
> 3. Returns a structured recommendation with cited evidence
>
> Two of the five tools wrap my existing FAISS RAG and XGBoost return-risk model. Three are mock external-data tools (competitor search, price history, demand trends).
>
> The trace panel is the unfair advantage. You can *see* the planner pick tools, the executor call them, the results stream back. Live debug + live demo in one UI.
>
> Built with LangGraph v1, MCP, FastAPI streaming SSE, Next.js. Eval harness with 30 gold queries scored by LLM-as-judge + trajectory F1.
>
> Live demo: <link>
> Source: <link>
> 90s Loom: <link>
>
> #AI #LangGraph #Engineering

---

## Option C — Lead with the lessons (recommended if you want comments)

> Three things I learned building an LLM agent that I didn't expect:
>
> 1. **The eval is the development loop.** I spent more time iterating on prompts *after* the eval report than I did writing the original prompts. Without the gold set + LLM-as-judge + trajectory F1, "improving the agent" is feelings.
>
> 2. **Trajectory is more diagnostic than the final answer.** If the agent calls the wrong tools, the answer is wrong by accident — even when it sounds plausible. My agent has 57% decision accuracy but 0.85 trajectory F1. Those numbers mean different things and both matter.
>
> 3. **Honest numbers + a clear "what we'd fix next" beats inflated metrics.** The 57% is the agent being over-confident on launch decisions. The eval surfaced it. Next prompt iteration targets it directly. Pretending it's 90% wouldn't help me ship.
>
> The project: an agent for Amazon sellers. LangGraph v1 + MCP + instructor + Groq. 5 tools, 2 of them wrap models I already had.
>
> Live demo + the eval methodology in the README: <link>
>
> #LLM #LangGraph #LLMOps #SoftwareEngineering

---

## Posting checklist

- [ ] Replace `<links>` and `<Loom link>` with real URLs
- [ ] Attach the demo GIF (from `docs/copilot-demo.gif`) as the first image
- [ ] Attach the eval table as a screenshot as the second image
- [ ] Hashtags at the bottom, ≤5
- [ ] Tag any specific hiring managers / recruiters who you've already talked to
- [ ] Post between Tue–Thu, 9-11am EST for best reach on LinkedIn
- [ ] Reply to the first 3-5 comments in the first hour to boost the algorithm

---

## Adapting for resume bullet

The spec's template, filled in with real numbers:

> **ListingLens Copilot — Agentic Seller Intelligence System**  
> Python, LangGraph v1, MCP, FastAPI, Next.js, Groq Llama 4, Claude (judge), DeepEval, Render, Vercel
>
> - Built a multi-agent system (Planner → Executor → Synthesizer) using LangGraph v1 and MCP, exposing 5 tools (RAG, XGBoost return-risk classifier, competitor data, pricing, trend signals) over the Model Context Protocol; agent autonomously plans research workflows for seller decisions and returns structured recommendations with cited evidence and SSE streaming to the frontend.
> - Designed a 30-query gold evaluation set with LLM-as-judge scoring (Claude Haiku as judge — different model family from Llama agent to avoid bias) and trajectory eval (tool-selection F1); full agent achieved **trajectory F1 of 0.85** (precision 0.92, recall 0.82) on the gold set, with p95 latency of 35s on Groq free tier.
> - Shipped Next.js 16 streaming UI with live agent-trace panel showing planning steps and per-tool results; deployed FastAPI backend on Render and frontend on Vercel with GitHub Actions running a 5-query smoke eval on every PR.
