# Eval Report — 2026-09-22 — no_tool

- **Variant:** `no_tool`
- **Queries:** 39 (36 success, 3 errors, 0 degraded)
- **Agent model:** `openai/gpt-oss-120b`
- **Executor model:** `openai/gpt-oss-20b`
- **RAG model:** `qwen/qwen3.8-27b`
- **Judge:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy — scored types `launch`, n=13 | **46.2%** (vs 46.2% majority baseline — always `needs_more_data`) |
| Decision accuracy — all types (informational), n=39 | 23.1% (vs 74.4% per-type-constant baseline) |
| Trajectory F1 (avg) | 0.000 |
| Trajectory precision (avg) | 0.000 |
| Trajectory recall (avg) | 0.000 |
| First-tool match rate | 0.0% |
| Latency p50 / p95 (s) | 35.9 / 40.4 |
| Error rate | 7.7% |
| Degraded (no model decision) | 0 |
| No-decision rate | 7.7% |

### Decision accuracy by query type

Only `launch` counts toward the headline. `expected_decision` is launch-decision vocabulary; for the other types there is no proposal to approve, so `go` degenerates into "the agent answered" and the label is near-constant. Those rows are shown as _informational_ — a swing is worth seeing, but it is not an accuracy claim. Each baseline below is the best constant predictor **within that type**, computed from this run's rows.

| Type | n | Correct | Accuracy | Majority baseline | Headline |
|---|---|---|---|---|---|
| improve | 15 | 2 | 13.3% | `go` 86.7% | informational |
| launch | 13 | 6 | 46.2% | `needs_more_data` 46.2% | **scored** |
| returns | 11 | 1 | 9.1% | `go` 90.9% | informational |

Across all 39 rows: a single constant (`go`) scores 64.1%, and the best constant per query_type scores 74.4%. An all-types accuracy at or below those is worse than a lookup table.

### LLM-as-judge

| Dimension | Avg score |
|---|---|
| Decision correctness | 0.283 |
| Evidence relevance | 0.153 |
| Anti-hallucination (higher=better) | 0.578 |
| Completeness | 0.844 |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 5.5s |
| launch_002 | launch | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 10.7s |
| launch_003 | launch | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 35.4s |
| launch_004 | launch | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 40.6s |
| launch_005 | launch | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 36.0s |
| launch_006 | launch | go | needs_more_data | ✗ | 0.00 | (none) | 20.2s |
| launch_007 | launch | no_go | needs_more_data | ✗ | 0.00 | (none) | 37.9s |
| launch_008 | launch | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 20.2s |
| launch_009 | launch | go | needs_more_data | ✗ | 0.00 | (none) | 40.4s |
| launch_010 | launch | no_go | needs_more_data | ✗ | 0.00 | (none) | 23.6s |
| launch_011 | launch | no_go | needs_more_data | ✗ | 0.00 | (none) | 40.4s |
| launch_012 | launch | no_go | needs_more_data | ✗ | 0.00 | (none) | 38.1s |
| launch_013 | launch | no_go | needs_more_data | ✗ | 0.00 | (none) | 20.0s |
| returns_001 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 38.3s |
| returns_002 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 38.5s |
| returns_003 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 37.2s |
| returns_004 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 18.5s |
| returns_005 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 38.9s |
| returns_006 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 21.2s |
| returns_007 | returns | go | ERROR | err | 0.00 | (none) | 19.9s |
| returns_008 | returns | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 8.4s |
| returns_009 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 35.9s |
| returns_010 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 37.1s |
| improve_001 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 38.8s |
| improve_002 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 36.5s |
| improve_003 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 17.6s |
| improve_004 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 32.9s |
| improve_005 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 34.6s |
| improve_006 | improve | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 35.7s |
| improve_007 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 38.4s |
| improve_008 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 36.0s |
| improve_009 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 37.9s |
| improve_010 | improve | needs_more_data | needs_more_data | ✓ | 0.00 | (none) | 36.2s |
| images_001 | improve | go | ERROR | err | 0.00 | (none) | 21.2s |
| images_002 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 2.6s |
| images_003 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 16.4s |
| images_004 | improve | go | ERROR | err | 0.00 | (none) | 45.4s |
| images_005 | improve | go | needs_more_data | ✗ | 0.00 | (none) | 20.6s |
| images_006 | returns | go | needs_more_data | ✗ | 0.00 | (none) | 37.7s |

## Failure modes

- **returns_007**: InstructorRetryException: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 3807, Requested 4269. Please try again in 570ms. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **images_001**: InstructorRetryException: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 3798, Requested 4209. Please try again in 52.5ms. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **images_004**: InstructorRetryException: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 5132, Requested 4163. Please try again in 9.712499999s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
