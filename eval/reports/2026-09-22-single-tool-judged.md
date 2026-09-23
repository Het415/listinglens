# Eval Report — 2026-09-22 — single_tool

- **Variant:** `single_tool`
- **Queries:** 39 (39 success, 0 errors, 0 degraded)
- **Agent model:** `openai/gpt-oss-120b`
- **Executor model:** `openai/gpt-oss-20b`
- **RAG model:** `qwen/qwen3.8-27b`
- **Judge:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy — scored types `launch`, n=13 | **46.2%** (vs 46.2% majority baseline — always `needs_more_data`) |
| Decision accuracy — all types (informational), n=39 | 43.6% (vs 74.4% per-type-constant baseline) |
| Trajectory F1 (avg) | 0.507 |
| Trajectory precision (avg) | 0.872 |
| Trajectory recall (avg) | 0.372 |
| First-tool match rate | 56.4% |
| Latency p50 / p95 (s) | 25.8 / 35.1 |
| Error rate | 0.0% |
| Degraded (no model decision) | 0 |
| No-decision rate | 0.0% |

### Decision accuracy by query type

Only `launch` counts toward the headline. `expected_decision` is launch-decision vocabulary; for the other types there is no proposal to approve, so `go` degenerates into "the agent answered" and the label is near-constant. Those rows are shown as _informational_ — a swing is worth seeing, but it is not an accuracy claim. Each baseline below is the best constant predictor **within that type**, computed from this run's rows.

| Type | n | Correct | Accuracy | Majority baseline | Headline |
|---|---|---|---|---|---|
| improve | 15 | 2 | 13.3% | `go` 86.7% | informational |
| launch | 13 | 6 | 46.2% | `needs_more_data` 46.2% | **scored** |
| returns | 11 | 9 | 81.8% | `go` 90.9% | informational |

Across all 39 rows: a single constant (`go`) scores 64.1%, and the best constant per query_type scores 74.4%. An all-types accuracy at or below those is worse than a lookup table.

### LLM-as-judge

| Dimension | Avg score |
|---|---|
| Decision correctness | 0.414 |
| Evidence relevance | 0.349 |
| Anti-hallucination (higher=better) | 0.805 |
| Completeness | 0.851 |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | needs_more_data | ✓ | 0.40 | review_qa | 6.1s |
| launch_002 | launch | needs_more_data | needs_more_data | ✓ | 0.50 | review_qa | 3.9s |
| launch_003 | launch | needs_more_data | needs_more_data | ✓ | 0.50 | review_qa | 21.6s |
| launch_004 | launch | needs_more_data | needs_more_data | ✓ | 0.40 | review_qa, review_qa | 30.0s |
| launch_005 | launch | needs_more_data | needs_more_data | ✓ | 0.40 | review_qa, review_qa | 34.7s |
| launch_006 | launch | go | needs_more_data | ✗ | 0.50 | review_qa | 25.8s |
| launch_007 | launch | no_go | needs_more_data | ✗ | 0.50 | review_qa | 31.3s |
| launch_008 | launch | needs_more_data | needs_more_data | ✓ | 0.40 | review_qa | 26.8s |
| launch_009 | launch | go | needs_more_data | ✗ | 0.50 | review_qa | 23.8s |
| launch_010 | launch | no_go | needs_more_data | ✗ | 0.50 | review_qa | 28.9s |
| launch_011 | launch | no_go | needs_more_data | ✗ | 0.00 | review_qa | 3.7s |
| launch_012 | launch | no_go | needs_more_data | ✗ | 0.00 | review_qa | 24.8s |
| launch_013 | launch | no_go | needs_more_data | ✗ | 0.50 | review_qa | 28.9s |
| returns_001 | returns | go | go | ✓ | 0.67 | review_qa | 12.6s |
| returns_002 | returns | go | needs_more_data | ✗ | 0.67 | review_qa | 12.2s |
| returns_003 | returns | go | go | ✓ | 0.67 | review_qa | 58.3s |
| returns_004 | returns | go | go | ✓ | 0.67 | review_qa | 27.0s |
| returns_005 | returns | go | go | ✓ | 0.50 | review_qa | 29.0s |
| returns_006 | returns | go | go | ✓ | 0.67 | review_qa | 28.6s |
| returns_007 | returns | go | go | ✓ | 0.50 | review_qa | 28.8s |
| returns_008 | returns | needs_more_data | go | ✗ | 0.67 | review_qa | 28.0s |
| returns_009 | returns | go | go | ✓ | 1.00 | review_qa | 39.3s |
| returns_010 | returns | go | go | ✓ | 0.67 | review_qa | 13.1s |
| improve_001 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 13.5s |
| improve_002 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 29.9s |
| improve_003 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 29.3s |
| improve_004 | improve | go | needs_more_data | ✗ | 0.50 | review_qa | 31.4s |
| improve_005 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 13.6s |
| improve_006 | improve | needs_more_data | needs_more_data | ✓ | 0.50 | review_qa | 29.4s |
| improve_007 | improve | go | needs_more_data | ✗ | 0.50 | review_qa | 11.9s |
| improve_008 | improve | go | needs_more_data | ✗ | 1.00 | review_qa | 15.4s |
| improve_009 | improve | go | needs_more_data | ✗ | 0.50 | review_qa | 15.5s |
| improve_010 | improve | needs_more_data | go | ✗ | 0.50 | review_qa | 28.0s |
| images_001 | improve | go | go | ✓ | 0.00 | review_qa | 17.6s |
| images_002 | improve | go | needs_more_data | ✗ | 0.00 | review_qa | 26.3s |
| images_003 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 5.3s |
| images_004 | improve | go | needs_more_data | ✗ | 0.50 | review_qa | 14.5s |
| images_005 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 16.8s |
| images_006 | returns | go | go | ✓ | 0.67 | review_qa | 12.1s |
