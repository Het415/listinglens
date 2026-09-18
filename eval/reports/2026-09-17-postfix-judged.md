# Eval Report — 2026-09-18 — full

- **Variant:** `full`
- **Queries:** 30 (25 success, 3 errors, 2 degraded)
- **Agent model:** `openai/gpt-oss-120b`
- **Executor model:** `openai/gpt-oss-20b`
- **RAG model:** `qwen/qwen3.8-27b`
- **Judge:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy | 56.7% |
| Trajectory F1 (avg) | 0.781 |
| Trajectory precision (avg) | 0.877 |
| Trajectory recall (avg) | 0.762 |
| First-tool match rate | 66.7% |
| Latency p50 / p95 (s) | 33.4 / 60.4 |
| Error rate | 10.0% |
| Degraded (no model decision) | 2 |
| No-decision rate | 16.7% |

### LLM-as-judge

| Dimension | Avg score |
|---|---|
| Decision correctness | 0.540 |
| Evidence relevance | 0.536 |
| Anti-hallucination (higher=better) | 0.860 |
| Completeness | 0.872 |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | needs_more_data | ✓ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 10.4s |
| launch_002 | launch | needs_more_data | needs_more_data | ✓ | 0.67 | competitor_search, trend_signal, price_history | 19.6s |
| launch_003 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 49.3s |
| launch_004 | launch | needs_more_data | no_go | ✗ | 1.00 | competitor_search, trend_signal, price_history, review_qa | 41.5s |
| launch_005 | launch | needs_more_data | needs_more_data | ✓ | 1.00 | trend_signal, competitor_search, price_history, review_qa | 58.0s |
| launch_006 | launch | go | needs_more_data | ✗ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 62.3s |
| launch_007 | launch | no_go | needs_more_data | ✗ | 0.86 | competitor_search, trend_signal, price_history, review_qa | 53.5s |
| launch_008 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal | 33.7s |
| launch_009 | launch | go | needs_more_data | ✗ | 0.67 | competitor_search, trend_signal, price_history | 43.1s |
| launch_010 | launch | no_go | no_go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 49.5s |
| returns_001 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa, review_qa | 33.8s |
| returns_002 | returns | go | go | ✓ | 0.67 | review_qa, review_qa | 81.3s |
| returns_003 | returns | go | go | ✓ | 0.67 | review_qa | 15.1s |
| returns_004 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 27.3s |
| returns_005 | returns | go | go | ✓ | 0.80 | predict_return_risk, review_qa | 22.5s |
| returns_006 | returns | go | go | ✓ | 0.67 | review_qa | 43.7s |
| returns_007 | returns | go | go | ✓ | 0.80 | predict_return_risk, review_qa | 56.3s |
| returns_008 | returns | needs_more_data | needs_more_data | ✓ | 0.50 | predict_return_risk, trend_signal | 13.8s |
| returns_009 | returns | go | go | ✓ | 0.67 | predict_return_risk, review_qa | 15.8s |
| returns_010 | returns | go | needs_more_data | ✗ | 0.67 | review_qa | 13.7s |
| improve_001 | improve | go | go | ✓ | 0.80 | review_qa, competitor_search, price_history | 40.6s |
| improve_002 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 19.3s |
| improve_003 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 16.7s |
| improve_004 | improve | go | needs_more_data | ✗ | 0.80 | competitor_search, price_history | 30.1s |
| improve_005 | improve | go | go | ✓ | 0.80 | review_qa, competitor_search, trend_signal | 34.3s |
| improve_006 | improve | needs_more_data | ERROR | err | 0.00 | (none) | 52.8s |
| improve_007 | improve | go | needs_more_data | ✗ | 0.80 | competitor_search, review_qa | 33.2s |
| improve_008 | improve | go | ERROR | err | 0.00 | (none) | 21.1s |
| improve_009 | improve | go | needs_more_data | ✗ | 0.50 | review_qa | 19.2s |
| improve_010 | improve | needs_more_data | ERROR | err | 0.00 | (none) | 23.5s |

## Failure modes

- **improve_006**: RateLimitError: Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1962. The request's expected output tokens exceed the enforced limit; reduce max_tokens (or the request's expected output) and try again. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing", 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_008**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199680, Requested 857. Please try again in 3m51.983999999s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_010**: RateLimitError: Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1049. The request's expected output tokens exceed the enforced limit; reduce max_tokens (or the request's expected output) and try again. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing", 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
