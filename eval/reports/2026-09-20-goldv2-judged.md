# Eval Report — 2026-09-20 — full

- **Variant:** `full`
- **Queries:** 33 (33 success, 0 errors, 0 degraded)
- **Agent model:** `openai/gpt-oss-120b`
- **Executor model:** `openai/gpt-oss-20b`
- **RAG model:** `qwen/qwen3.8-27b`
- **Judge:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy — scored types `launch`, n=13 | **69.2%** (vs 46.2% majority baseline — always `needs_more_data`) |
| Decision accuracy — all types (informational), n=33 | 66.7% (vs 69.7% per-type-constant baseline) |
| Trajectory F1 (avg) | 0.798 |
| Trajectory precision (avg) | 0.849 |
| Trajectory recall (avg) | 0.811 |
| First-tool match rate | 60.6% |
| Latency p50 / p95 (s) | 35.5 / 53.9 |
| Error rate | 0.0% |
| Degraded (no model decision) | 0 |
| No-decision rate | 0.0% |

### Decision accuracy by query type

Only `launch` counts toward the headline. `expected_decision` is launch-decision vocabulary; for the other types there is no proposal to approve, so `go` degenerates into "the agent answered" and the label is near-constant. Those rows are shown as _informational_ — a swing is worth seeing, but it is not an accuracy claim. Each baseline below is the best constant predictor **within that type**, computed from this run's rows.

| Type | n | Correct | Accuracy | Majority baseline | Headline |
|---|---|---|---|---|---|
| improve | 10 | 6 | 60.0% | `go` 80.0% | informational |
| launch | 13 | 9 | 69.2% | `needs_more_data` 46.2% | **scored** |
| returns | 10 | 7 | 70.0% | `go` 90.0% | informational |

Across all 33 rows: a single constant (`go`) scores 57.6%, and the best constant per query_type scores 69.7%. An all-types accuracy at or below those is worse than a lookup table.

### LLM-as-judge

| Dimension | Avg score |
|---|---|
| Decision correctness | 0.603 |
| Evidence relevance | 0.548 |
| Anti-hallucination (higher=better) | 0.824 |
| Completeness | 0.870 |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | needs_more_data | ✓ | 1.00 | competitor_search, trend_signal, price_history, review_qa | 10.1s |
| launch_002 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 49.0s |
| launch_003 | launch | needs_more_data | needs_more_data | ✓ | 0.67 | trend_signal, competitor_search, price_history | 34.3s |
| launch_004 | launch | needs_more_data | no_go | ✗ | 0.86 | trend_signal, competitor_search, price_history | 42.2s |
| launch_005 | launch | needs_more_data | needs_more_data | ✓ | 1.00 | competitor_search, trend_signal, price_history, review_qa | 51.4s |
| launch_006 | launch | go | needs_more_data | ✗ | 0.67 | competitor_search, trend_signal, price_history | 33.2s |
| launch_007 | launch | no_go | go | ✗ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 35.3s |
| launch_008 | launch | needs_more_data | needs_more_data | ✓ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 53.3s |
| launch_009 | launch | go | needs_more_data | ✗ | 0.67 | competitor_search, price_history, trend_signal | 46.1s |
| launch_010 | launch | no_go | no_go | ✓ | 0.86 | competitor_search, review_qa, trend_signal, price_history | 40.0s |
| launch_011 | launch | no_go | no_go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 49.2s |
| launch_012 | launch | no_go | no_go | ✓ | 0.80 | competitor_search, trend_signal, price_history | 31.6s |
| launch_013 | launch | no_go | no_go | ✓ | 0.67 | competitor_search, trend_signal, price_history | 23.3s |
| returns_001 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 36.2s |
| returns_002 | returns | go | go | ✓ | 0.80 | review_qa, predict_return_risk, competitor_search | 41.4s |
| returns_003 | returns | go | go | ✓ | 0.67 | review_qa | 32.7s |
| returns_004 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 41.9s |
| returns_005 | returns | go | go | ✓ | 0.80 | predict_return_risk, review_qa | 35.5s |
| returns_006 | returns | go | needs_more_data | ✗ | 0.67 | review_qa | 16.7s |
| returns_007 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa, competitor_search | 76.9s |
| returns_008 | returns | needs_more_data | go | ✗ | 1.00 | predict_return_risk, review_qa | 26.8s |
| returns_009 | returns | go | go | ✓ | 0.67 | predict_return_risk, review_qa | 15.8s |
| returns_010 | returns | go | needs_more_data | ✗ | 0.67 | review_qa | 36.0s |
| improve_001 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 21.3s |
| improve_002 | improve | go | go | ✓ | 0.80 | review_qa, competitor_search, price_history | 54.8s |
| improve_003 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 19.8s |
| improve_004 | improve | go | go | ✓ | 1.00 | competitor_search, review_qa, price_history | 46.1s |
| improve_005 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 26.6s |
| improve_006 | improve | needs_more_data | needs_more_data | ✓ | 0.67 | price_history, competitor_search, trend_signal | 40.2s |
| improve_007 | improve | go | go | ✓ | 1.00 | competitor_search, review_qa, price_history | 42.6s |
| improve_008 | improve | go | go | ✓ | 0.67 | review_qa, competitor_search | 35.5s |
| improve_009 | improve | go | needs_more_data | ✗ | 0.50 | review_qa | 8.8s |
| improve_010 | improve | needs_more_data | needs_more_data | ✓ | 0.67 | trend_signal, price_history, competitor_search | 18.1s |
