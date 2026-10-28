# ListingLens Copilot — Evaluation Harness

This directory holds the evaluation harness for the ListingLens Copilot agent: the gold set, the runner, baselines, trajectory scoring, LLM judges and the generated reports. Everything described here is implemented.

---

## What the Copilot does

ListingLens today is a **passive** RAG system: a seller asks about their product, the system retrieves matching review chunks, and an LLM answers. Fixed pipeline.

ListingLens Copilot is an **active** agent. Given a seller question — "Should I launch a stainless variant?", "Why are returns spiking on this SKU?", "How do I improve this listing?" — the agent:

1. **Plans** which evidence it needs (which tools to call, in what order)
2. **Executes** tools autonomously (6 of them: review_qa, predict_return_risk, competitor_search, price_history, trend_signal, image_audit)
3. **Synthesizes** a structured recommendation with `decision`, `confidence`, cited `evidence`, listed `risks`, `suggested_next_actions` and `evidence_gaps`

Two of the six tools (`review_qa`, `predict_return_risk`) are powered by the **existing** ListingLens models — the FAISS RAG over real Amazon reviews and the XGBoost return-risk classifier. The classifier is trained on synthetic profiles against a proxy label, and it scores all 12 catalog products LOW (0.0–0.4%). `image_audit` applies deterministic main-image rules to uploaded images. The three external-data tools (`competitor_search`, `price_history`, `trend_signal`) are mocked, seeded with realistic data for the 12 supported ASINs.

Why this matters: most agent demos are toys ("give me a recipe"). This one is grounded in a real domain with measurable outcomes.

---

## Evaluation philosophy

You cannot unit-test an agent the way you test a function. Outputs are stochastic; "correct" is fuzzy. So we evaluate along **three independent axes** and report all three honestly — including failures.

### Axis 1 — Output quality (LLM-as-judge)

A second LLM scores each agent response with DeepEval's `GEval`, normalised to 0-1. To avoid same-family bias, the judge model is a *different model family* than the agent (agent: Groq `gpt-oss-120b`; judge: Anthropic `claude-haiku-4-5-20251001` by default). Set `JUDGE_PROVIDER=openai` to use `gpt-4o-mini` instead, or pass `--no-judge` to skip judging entirely.

Four scored dimensions per query:
- **Decision correctness** — does the agent's `decision` match the gold `expected_decision`?
- **Evidence relevance** — do the cited evidence snippets match the gold `expected_evidence_themes`?
- **Hallucination** — is each claim supported by the agent's cited snippets? The judge sees only those snippets, never the raw tool outputs, so this measures internal consistency, not grounding.
- **Completeness** — does the recommendation address all critical aspects of the question?

**Judge scores aren't used as a headline.** Besides the hallucination caveat, the evidence-relevance judge is shown the expected decision, so its score tracks agreement with the gold answer. Fix both before trusting either number.

### Axis 2 — Trajectory correctness

Often more diagnostic than the final answer. If the agent called the wrong tools, the answer is wrong by accident even if it sounds plausible.

For each query, compare `actual_tools_called` (extracted from LangGraph trace) against gold `expected_tools`. Compute **F1 over the tool set** plus an **ordering bonus** (+0.1 if the first tool matches expected).

### Axis 3 — Operational metrics

- **Latency** — p50 and p95 wall-clock
- **Error rate** — rows that raised
- **Degraded rows** — a stage gave up and the answer was assembled without the model. Flagged, and never scored as correct
- **No-decision rate** — errored plus degraded rows
- Not tracked yet: tokens and cost per query

A correct but $2/query agent is a failed agent. Operational metrics regressions are real bugs, even when quality looks fine.

---

## Baselines

If the full agent doesn't beat these, the architecture isn't earning its complexity. Both are implemented in `baselines.py` and have been run.

- **`no_tool`** — the same LLM with no tools: two calls, a plain answer then a structured one. The "minimum useful" floor.
- **`single_tool`** — agent only has `review_qa`. Shows the lift from adding tools beyond what the existing `/chat` endpoint already provides.

**Current result: it doesn't beat `no_tool` on launch decisions.** Full agent 5/13 (right in both runs); `no_tool` 6/13 in each of three runs, always `needs_more_data`, exactly the constant floor; exact McNemar p = 1.0. See [Results](#results).

---

## Files in this directory

| File | Status | Purpose |
|---|---|---|
| `gold_set.jsonl` | ✅ | 39 hand-crafted queries with expected outputs |
| `run_eval.py` | ✅ | Main eval runner — invokes the agent (or a baseline) on each gold query, scores it against runtime baselines, stamps provenance |
| `baselines.py` | ✅ | `no_tool` and `single_tool` |
| `judges.py` | ✅ | DeepEval `GEval` LLM-as-judge metrics (Claude Haiku 4.5 by default; `JUDGE_PROVIDER=openai` switches to GPT-4o-mini) |
| `trajectory_eval.py` | ✅ | F1 + ordering bonus over actual vs expected tool sets |
| `compare_reports.py` | ✅ | Row-by-row diff of two reports |
| `reports/` | ✅ | Generated Markdown + JSONL per run, named `YYYY-MM-DD-{tag}.md`; each records the git commit, gold sha256 and prompts sha256 |

---

## Gold set design rationale

The gold set is intentionally diverse along several dimensions:

**Query types (13 launch, 11 returns, 15 improve):**
- `launch` — "should I launch a variant?" — 6 of 13 are `needs_more_data`, because real launch decisions often need data beyond these tools
- `returns` — "why are returns spiking?" — diagnostic queries, mostly `go` (action plan)
- `improve` — "how do I improve this listing?" — mostly `go` (concrete recommendations)

**Decision distribution** (rebalanced 2026-09-17 — see the audit note below):
| Decision | Count | Why |
|---|---|---|
| `go` | 25 | Most returns/improve queries have clear action plans (19, plus the six image rows added 2026-09-20) |
| `needs_more_data` | 9 | Most launch queries + a few honest "we don't have that data" cases (e.g., temporal trends, BSR causality) |
| `no_go` | 5 | Tests the agent's ability to actively decline. All inside `launch`, the only type where declining is meaningful: `launch_007` (AirPods sport variant), `launch_010` (Echo Dot clock — Amazon already sells it), `launch_011` (cheaper Fire stick — Amazon's own Lite is already at the same price), `launch_012` (Wi-Fi 6E stick — the 4K Max ships it and its top complaint is "Wi-Fi 6E underused"), `launch_013` (portable Echo Dot — category −17.1% YoY and saturated) |

⚠️ **Audit, 2026-09-17 — read before trusting a decision-accuracy number.** `expected_decision` used to be near-determined by `query_type` (returns → `go` 9/10, improve → `go` 8/10, launch → `needs_more_data` 6/10). A three-entry lookup table scored **76.7%** against the agent's 60.0%, and a flat "always `go`" scored 63.3%. Two things were wrong: `go/no_go/needs_more_data` is *launch* vocabulary that degenerates on diagnostic queries, and `no_go` had only 2 instances so the capability was unmeasurable.

Fixed by (a) scoring only `launch` in the headline — `DECISION_SCORED_TYPES` in `run_eval.py` — with returns/improve reported as informational, and (b) adding three `no_go` cases. The launch baseline fell from 60.0% to **46.2%**, so the scored benchmark is now materially harder to guess. Every report prints these floors next to the accuracy, derived from the gold set at runtime, so this cannot silently drift again.

**Tool-set discrimination:**
The 39 queries do not all expect the same tools. `review_qa` is expected on all but five (`launch_011`, `launch_012`, `images_001`-`003`). `predict_return_risk` is mostly returns queries. `trend_signal` and `competitor_search` cluster on launch queries. The trajectory F1 has real discriminative signal.

**ASIN coverage:**
All 12 supported ASINs are exercised, at 2-4 queries each. Queries are matched to each product's *actual* complaint signature from `data/processed/features_*.json` — e.g., Ring Doorbell's "What's driving negative reviews?" query expects evidence around customer service, setup/installation, and connectivity.

⚠️ Those `features_*.json` shares (Ring's customer-service topic is 17.3% negative since the 2026-09-23 feature fixes; it read 44.8% before them) are **real but not evidenceable**. No tool reads that block — `_loader.asin_summary()` exists but nothing under `tools/` calls it — and `review_qa` returns 5 retrieved chunks out of ~2,900, which cannot derive a share. Four gold rows used to demand those percentages and were unwinnable by construction; their themes now ask for the complaint category to be named and quoted instead. Keep new themes on the evidenceable side of that line. Quantitative themes ARE legitimate where a tool genuinely returns a number — `predict_return_risk` returns `risk_pct`, so risk figures stay quantitative.

**Honesty tests:**
Two queries (`returns_008` Panasonic — "trending over time", `improve_010` Fire TV HD — "BSR drop causes") test whether the agent honestly admits limitations of the data instead of fabricating temporal trends or BSR causality.

---

## How to run the eval

```bash
# Full run over every gold query, produces eval/reports/YYYY-MM-DD-{tag}.md
python -m eval.run_eval --gold eval/gold_set.jsonl

# Baselines
python -m eval.run_eval --baseline=no_tool
python -m eval.run_eval --baseline=single_tool

# CI smoke eval (runs on PRs via GitHub Actions). The 5 rows are a
# stratified pick, not the first 5; the job exits 2 if any row errors or degrades
python -m eval.run_eval --limit 5 --no-judge --output-tag pr-smoke
```

### After landing a prompt/schema change — measure the lift

When you change anything in the synthesizer, planner, or schemas, the
ritual is: re-run the eval, then diff against the previous report.

```bash
# 1. Run the eval (Groq free tier: 200k tokens/day PER MODEL, rolling window)
python -m eval.run_eval

# 2. Diff the new report against the previous one. By default this
#    auto-picks the two most-recently-modified .jsonl files in
#    eval/reports/ (excluding baselines).
python -m eval.compare_reports

# 3. Explicit before/after when comparing across non-adjacent runs
python -m eval.compare_reports \
  eval/reports/2026-09-23-launch-full-k1.jsonl \
  eval/reports/2026-09-25-launch-full-k2.jsonl

# 4. Markdown output for pasting into PR descriptions
python -m eval.compare_reports --markdown
```

The diff highlights per-query-type accuracy deltas, lists every query
that flipped (newly passing / newly failing), and flags trajectory F1
and judge-score regressions. Use it as a regression gate — a prompt
change that improves launch accuracy but tanks returns accuracy should
show up here, not in the wild.

---

## Results

**Current headline: the repeated-runs launch series (2026-09-23 → 10-01, code frozen at `b1eb690d`, `--no-judge`).** The 13 `launch` rows of `gold_set.jsonl` were run as the `--gold` file; each run's keep/discard rule was written before it ran.

| | Kept runs | Launch decision accuracy | 95% Wilson interval |
|---|---|---|---|
| Full agent | 2 (`2026-09-23-launch-full-k1`, `2026-09-25-launch-full-k2`) | **5/13** right in both (7/13, 6/13 per run) | 17.7–64.5% |
| `no_tool` | 3 (`2026-09-27-`, `2026-09-28-`, `2026-10-01-launch-notool-k*`) | 6/13 in every run, all `needs_more_data` | 23.2–70.9% |
| Constant floor | — | 6/13 (always `needs_more_data`) | 23.2–70.9% |

Paired: agent-only right 1, `no_tool`-only right 2, exact McNemar p = 1.0. Full-agent runs: trajectory F1 0.830 / 0.816, first-tool match 38.5%, latency p50 47.5 / 42.1 s, 0 errored and 0 degraded rows. Two runs of identical code agreed on 9 of 13 rows.

**Reading the numbers honestly:**

- **No measurable lift on launch decisions.** The intervals overlap almost completely, so this doesn't show the agent is worse; the benchmark can't tell it apart from always hedging.
- **The agent under-commits.** `go` is *nearly* unreachable on launch questions because of a contradiction in `prompts.py`: `evidence_gaps` must always be populated, and a non-empty `evidence_gaps` forces `needs_more_data`. Launch rows answered `go` only 1–3 times per run. This corrects an older note here that called the failure over-confidence; that was disproven on 2026-09-17, when a judged run showed 8 hedges against 3 over-commits.
- **Trajectory is not the strong point it was once called.** Recall is high (the expected tools are usually called), but the first tool matches the gold order on only 38.5% of rows.
- **The earlier 69.2% headline** (`2026-09-20-goldv2-judged.md`) is not comparable: 3 of its 13 launch rows were the synthesizer's few-shot examples, quoted with their gold answers (removed in `2ffa1f05`), and that run recorded no commit.

Earlier snapshots, kept for history: the first full-agent run [reports/2026-05-16-full.md](reports/2026-05-16-full.md) (30 rows, 56.7%, before the launch-only scoring and the leakage fix), and the first baseline runs `2026-09-21-no-tool-judged.md` and `2026-09-22-single-tool-judged.md`. Budget note: the Groq free tier is **200k tokens/day per model** on a rolling window, and one full 39-query run comes close to it, so budget one full run per day.

---

## 2026-09-20 — six `image_audit` rows added (33 → 39)

Four positive rows (`images_001`-`004`) and **two negative rows**
(`images_005`, `images_006`). The negative rows are the highest-signal
addition: `images_005` is a copy question that must *not* pull `image_audit`
just because it says "listing", and `images_006` is a returns diagnosis that
must not be hijacked by attached images.

**⚠️ Read the baselines before comparing any run to `2026-09-20-goldv2-judged.md`.**

| Floor | Before (33 rows) | After (39 rows) |
|---|---|---|
| Launch-only, always-`needs_more_data` — **the published headline floor** | 46.2% | **46.2% (unchanged)** |
| All-types, always-`go` | 57.6% | 64.1% |
| All-types, best-constant-per-type lookup | 69.7% | **74.4%** |

All six new rows are `improve` or `returns`, so `DECISION_SCORED_TYPES`
(launch-only, 13 rows) is untouched and the **headline decision accuracy
remains directly comparable** across the change. That was deliberate: a new
`QueryType` would have needed a fourth synthesizer rubric and a fourth
baseline on a benchmark affordable about once a day.

The *informational* all-types figure is **not** comparable. Its lookup-table
floor rose 4.7 points because the added rows are `go` in types where `go`
already dominated, so identical agent behaviour will score further below its
floor than before. This is the same confound the README documents for the
60% → 69.2% move, running in the opposite direction — do not read a drop there
as a regression.

**Primary metric for the new rows is a count, not an aggregate.** Per the
build plan and the ~11-row noise floor, report `image_audit` called on N of 4
positive rows and 0 of 2 negative rows. First measurement, 2026-09-20, single
runs: **2/2 positives tested, 2/2 negatives correct** —
`images_002` used `image_audit` alone (no padding), `images_005` used
`competitor_search, review_qa, trend_signal`, `images_006` used
`predict_return_risk, review_qa`.
