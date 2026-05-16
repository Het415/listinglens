# ListingLens Copilot — Evaluation Harness

This directory holds the evaluation harness for the ListingLens Copilot agent extension. It is scaffolded in Stage 0 (gold-set design) and fully implemented in Stage 4.

---

## What the Copilot does (elevator pitch — refines for Stage 6 README)

ListingLens today is a **passive** RAG system: a seller asks about their product, the system retrieves matching review chunks, and an LLM answers. Fixed pipeline.

ListingLens Copilot is an **active** agent. Given a seller question — "Should I launch a stainless variant?", "Why are returns spiking on this SKU?", "How do I improve this listing?" — the agent:

1. **Plans** which evidence it needs (which tools to call, in what order)
2. **Executes** tools autonomously (5 of them: review_qa, predict_return_risk, competitor_search, price_history, trend_signal)
3. **Synthesizes** a structured recommendation with `decision`, `confidence`, cited `evidence`, listed `risks`, and `suggested_next_actions`

Two of the five tools (`review_qa`, `predict_return_risk`) are powered by the **existing** ListingLens models — the FAISS RAG over real Amazon reviews and the XGBoost return-risk classifier. The three external-data tools (`competitor_search`, `price_history`, `trend_signal`) are mocked for v1, seeded with realistic data for the 12 supported ASINs.

Why this matters: most agent demos are toys ("give me a recipe"). This one is grounded in a real domain with measurable outcomes.

---

## Evaluation philosophy

You cannot unit-test an agent the way you test a function. Outputs are stochastic; "correct" is fuzzy. So we evaluate along **three independent axes** and report all three honestly — including failures.

### Axis 1 — Output quality (LLM-as-judge)

A second LLM scores each agent response on a 0-5 rubric. To avoid same-family bias, the judge model is a *different model family* than the agent (agent: Groq Llama 3.3 70B; judge: GPT-4o-mini).

Four scored dimensions per query:
- **Decision correctness** — does the agent's `decision` match the gold `expected_decision`?
- **Evidence relevance** — do the cited evidence snippets match the gold `expected_evidence_themes`?
- **Hallucination** — does any claim in the recommendation lack support in actual tool outputs?
- **Completeness** — does the recommendation address all critical aspects of the question?

### Axis 2 — Trajectory correctness

Often more diagnostic than the final answer. If the agent called the wrong tools, the answer is wrong by accident even if it sounds plausible.

For each query, compare `actual_tools_called` (extracted from LangGraph trace) against gold `expected_tools`. Compute **F1 over the tool set** plus an **ordering bonus** (+0.1 if the first tool matches expected).

### Axis 3 — Operational metrics

- **Tokens** per query (input + output)
- **Cost** per query in USD
- **Latency** — p50, p95, p99 wall-clock
- **Error rate** — tool failures, parse failures, timeouts

A correct but $2/query agent is a failed agent. Operational metrics regressions are real bugs, even when quality looks fine.

---

## Baselines (Stage 4 implements these)

The full agent must beat both baselines on a composite score. If it doesn't, the architecture isn't earning its complexity.

- **`no_tool`** — single LLM call, no tools available. The "minimum useful" floor.
- **`single_tool`** — agent only has `review_qa`. Shows the lift from adding tools beyond what the existing `/chat` endpoint already provides.

---

## Files in this directory

| File | Status | Purpose |
|---|---|---|
| `gold_set.jsonl` | **Stage 0 ✅** | 30 hand-crafted queries with expected outputs |
| `run_eval.py` | Stage 4 | Main eval runner — invokes agent on each gold query, records results |
| `judges.py` | Stage 4 | DeepEval `GEval` LLM-as-judge metrics (GPT-4o-mini as judge) |
| `trajectory_eval.py` | Stage 4 | F1 + ordering bonus over actual vs expected tool sets |
| `reports/` | Stage 4 | Generated Markdown reports per run, named `YYYY-MM-DD.md` |

---

## Gold set design rationale

The gold set is intentionally diverse along several dimensions:

**Query types (10 each):**
- `launch` — "should I launch a variant?" — most should be `needs_more_data` because real launch decisions need data beyond 5 tools
- `returns` — "why are returns spiking?" — diagnostic queries, mostly `go` (action plan)
- `improve` — "how do I improve this listing?" — mostly `go` (concrete recommendations)

**Decision distribution (deliberately not all "go"):**
| Decision | Count | Why |
|---|---|---|
| `go` | 19 | Most returns/improve queries have clear action plans |
| `needs_more_data` | 9 | Most launch queries + a few honest "we don't have that data" cases (e.g., temporal trends, BSR causality) |
| `no_go` | 2 | Tests agent's ability to actively decline. `launch_007` (AirPods sport variant — brand issue + saturated segment) and `launch_010` (Echo Dot clock — Amazon already sells this) |

**Tool-set discrimination:**
The 30 queries do not all expect the same tools. `review_qa` is universal (always evidence). `predict_return_risk` is mostly returns queries. `trend_signal` and `competitor_search` cluster on launch queries. The trajectory F1 has real discriminative signal.

**ASIN coverage:**
All 12 supported ASINs are exercised. Queries are matched to each product's *actual* complaint signature from `data/processed/features_*.json` — e.g., Ring Doorbell's "What's driving negative reviews?" query expects evidence around customer service (44.8% negative in real data), setup/installation, and connectivity.

**Honesty tests:**
Two queries (`returns_008` Panasonic — "trending over time", `improve_010` Fire TV HD — "BSR drop causes") test whether the agent honestly admits limitations of the data instead of fabricating temporal trends or BSR causality.

---

## How to run the eval (Stage 4 will implement)

```bash
# Full 30-query run, produces eval/reports/YYYY-MM-DD.md
python -m eval.run_eval --gold eval/gold_set.jsonl

# Baselines
python -m eval.run_eval --baseline=no_tool
python -m eval.run_eval --baseline=single_tool

# CI smoke eval (5 queries, runs on PRs via GitHub Actions)
python -m eval.run_eval --gold eval/gold_set.jsonl --limit 5
```

---

## Results (filled in at Stage 4)

```
| Metric             | Full agent | Single-tool | No-tool |
|--------------------|------------|-------------|---------|
| Decision accuracy  |    TBD     |    TBD      |   TBD   |
| Avg trajectory F1  |    TBD     |    TBD      |   N/A   |
| Avg tokens/query   |    TBD     |    TBD      |   TBD   |
| p95 latency        |    TBD     |    TBD      |   TBD   |
| $/query            |    TBD     |    TBD      |   TBD   |
```

Latest report: `reports/` (none yet — Stage 4)
