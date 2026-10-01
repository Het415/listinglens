# Eval Report — 2026-09-25 — full

- **Variant:** `full`
- **Queries:** 13 (13 success, 0 errors, 0 degraded)
- **Agent model:** `openai/gpt-oss-120b`
- **Executor model:** `openai/gpt-oss-20b`
- **RAG model:** `qwen/qwen3.8-27b`
- **Judge:** _not run_ (`--no-judge`) — no LLM-as-judge scores in this report
- **Commit:** `b1eb690decbe386b517fccc686609c7b9f170279` · **gold** sha256 `68b4178ff2cf` · **prompts.py** sha256 `0b5d9494007a` · **deepeval** `4.2.3`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy — scored types `launch`, n=13 | **46.2%** (vs 46.2% majority baseline — always `needs_more_data`) |
| Decision accuracy — all types (informational), n=13 | 46.2% (vs 46.2% per-type-constant baseline) |
| Trajectory F1 (avg) | 0.816 |
| Trajectory precision (avg) | 0.814 |
| Trajectory recall (avg) | 0.840 |
| First-tool match rate | 38.5% |
| Latency p50 / p95 (s) | 42.1 / 67.3 |
| Error rate | 0.0% |
| Degraded (no model decision) | 0 |
| No-decision rate | 0.0% |

### Decision accuracy by query type

Only `launch` counts toward the headline. `expected_decision` is launch-decision vocabulary; for the other types there is no proposal to approve, so `go` degenerates into "the agent answered" and the label is near-constant. Those rows are shown as _informational_ — a swing is worth seeing, but it is not an accuracy claim. Each baseline below is the best constant predictor **within that type**, computed from this run's rows.

| Type | n | Correct | Accuracy | Majority baseline | Headline |
|---|---|---|---|---|---|
| launch | 13 | 6 | 46.2% | `needs_more_data` 46.2% | **scored** |

Across all 13 rows: a single constant (`needs_more_data`) scores 46.2%, and the best constant per query_type scores 46.2%. An all-types accuracy at or below those is worse than a lookup table.

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, trend_signal, price_history | 6.8s |
| launch_002 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 35.7s |
| launch_003 | launch | needs_more_data | needs_more_data | ✓ | 0.67 | competitor_search, price_history, trend_signal | 45.5s |
| launch_004 | launch | needs_more_data | no_go | ✗ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 48.7s |
| launch_005 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, trend_signal, price_history | 40.8s |
| launch_006 | launch | go | go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 90.7s |
| launch_007 | launch | no_go | go | ✗ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 51.7s |
| launch_008 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal | 39.4s |
| launch_009 | launch | go | needs_more_data | ✗ | 0.67 | competitor_search, trend_signal, price_history | 47.8s |
| launch_010 | launch | no_go | needs_more_data | ✗ | 0.67 | competitor_search, trend_signal, price_history | 42.1s |
| launch_011 | launch | no_go | needs_more_data | ✗ | 1.00 | competitor_search, price_history, trend_signal | 36.5s |
| launch_012 | launch | no_go | needs_more_data | ✗ | 0.80 | competitor_search, trend_signal, price_history | 37.0s |
| launch_013 | launch | no_go | needs_more_data | ✗ | 0.67 | competitor_search, trend_signal, price_history | 47.5s |
