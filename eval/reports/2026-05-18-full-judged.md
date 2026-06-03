# Eval Report — 2026-05-18 — full

- **Variant:** `full`
- **Queries:** 30 (20 success, 10 errors)
- **Agent model:** `meta-llama/llama-4-scout-17b-16e-instruct`
- **Judge model:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy | 40.0% |
| Trajectory F1 (avg) | 0.913 |
| Trajectory precision (avg) | 0.926 |
| Trajectory recall (avg) | 0.925 |
| First-tool match rate | 50.0% |
| Latency p50 / p95 (s) | 12.1 / 34.4 |
| Error rate | 33.3% |

### LLM-as-judge

| Dimension | Avg score |
|---|---|
| Decision correctness | 0.405 |
| Evidence relevance | 0.450 |
| Anti-hallucination (higher=better) | 0.730 |
| Completeness | 0.785 |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | go | ✗ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 10.9s |
| launch_002 | launch | needs_more_data | no_go | ✗ | 0.75 | predict_return_risk, competitor_search, trend_signal, review_qa, price_history | 9.7s |
| launch_003 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 33.2s |
| launch_004 | launch | needs_more_data | needs_more_data | ✓ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 32.9s |
| launch_005 | launch | needs_more_data | go | ✗ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 34.3s |
| launch_006 | launch | go | go | ✓ | 1.00 | competitor_search, trend_signal, review_qa | 24.1s |
| launch_007 | launch | no_go | go | ✗ | 0.67 | competitor_search, trend_signal, price_history | 27.6s |
| launch_008 | launch | needs_more_data | go | ✗ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 33.0s |
| launch_009 | launch | go | go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 34.5s |
| launch_010 | launch | no_go | go | ✗ | 0.86 | review_qa, competitor_search, trend_signal, price_history | 32.3s |
| returns_001 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 17.8s |
| returns_002 | returns | go | go | ✓ | 1.00 | review_qa, predict_return_risk | 18.5s |
| returns_003 | returns | go | go | ✓ | 1.00 | review_qa, predict_return_risk | 18.8s |
| returns_004 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 17.2s |
| returns_005 | returns | go | go | ✓ | 0.80 | predict_return_risk, review_qa | 18.5s |
| returns_006 | returns | go | no_go | ✗ | 0.67 | review_qa | 277.9s |
| returns_007 | returns | go | go | ✓ | 0.80 | predict_return_risk, review_qa | 5.7s |
| returns_008 | returns | needs_more_data | go | ✗ | 1.00 | review_qa, predict_return_risk | 6.4s |
| returns_009 | returns | go | go | ✓ | 1.00 | review_qa | 5.5s |
| returns_010 | returns | go | go | ✓ | 1.00 | review_qa, predict_return_risk | 7.4s |
| improve_001 | improve | go | ERROR | err | 0.00 | (none) | 13.2s |
| improve_002 | improve | go | ERROR | err | 0.00 | (none) | 0.3s |
| improve_003 | improve | go | ERROR | err | 0.00 | (none) | 0.3s |
| improve_004 | improve | go | ERROR | err | 0.00 | (none) | 0.3s |
| improve_005 | improve | go | ERROR | err | 0.00 | (none) | 0.3s |
| improve_006 | improve | needs_more_data | ERROR | err | 0.00 | (none) | 0.3s |
| improve_007 | improve | go | ERROR | err | 0.00 | (none) | 0.3s |
| improve_008 | improve | go | ERROR | err | 0.00 | (none) | 0.3s |
| improve_009 | improve | go | ERROR | err | 0.00 | (none) | 0.3s |
| improve_010 | improve | needs_more_data | ERROR | err | 0.00 | (none) | 0.3s |

## Failure modes

- **improve_001**: InstructorRetryException: <failed_attempts>

<generation number="1">
<exception>
    Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499483, Requested 3865. Please try again in 9m38.5344s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
</exception>
<completion>
    None
</completion>
</generation>

<generation number="2">
<exception>
    Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499482, Requested 3847. Please try again in 9m35.2512s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
</exception>
<completion>
    None
</completion>
</generation>

</failed_attempts>

<last_exception>
    Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499482, Requested 3847. Please try again in 9m35.2512s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
</last_exception>
- **improve_002**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499481, Requested 1779. Please try again in 3m37.728s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_003**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499479, Requested 1474. Please try again in 2m44.678399999s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_004**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499477, Requested 1826. Please try again in 3m45.158399999s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_005**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499475, Requested 1781. Please try again in 3m37.0368s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_006**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499474, Requested 1778. Please try again in 3m36.3456s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_007**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499472, Requested 1832. Please try again in 3m45.3312s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_008**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499470, Requested 1477. Please try again in 2m43.6416s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_009**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499469, Requested 1477. Please try again in 2m43.4688s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- **improve_010**: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` on tokens per day (TPD): Limit 500000, Used 499467, Requested 1471. Please try again in 2m42.0864s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
