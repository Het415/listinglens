# Eval Report — 2026-05-17 — full

- **Variant:** `full`
- **Queries:** 30 (30 success, 0 errors)
- **Agent model:** `meta-llama/llama-4-scout-17b-16e-instruct`
- **Judge model:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy | 60.0% |
| Trajectory F1 (avg) | 0.800 |
| Trajectory precision (avg) | 0.872 |
| Trajectory recall (avg) | 0.786 |
| First-tool match rate | 60.0% |
| Latency p50 / p95 (s) | 18.6 / 34.1 |
| Error rate | 0.0% |

### LLM-as-judge

| Dimension | Avg score |
|---|---|
| Decision correctness | N/A |
| Evidence relevance | N/A |
| Anti-hallucination (higher=better) | N/A |
| Completeness | N/A |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | go | ✗ | 0.86 | competitor_search, trend_signal, review_qa | 9.3s |
| launch_002 | launch | needs_more_data | no_go | ✗ | 0.33 | predict_return_risk, competitor_search, trend_signal | 4.3s |
| launch_003 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 14.4s |
| launch_004 | launch | needs_more_data | no_go | ✗ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 32.4s |
| launch_005 | launch | needs_more_data | go | ✗ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 32.8s |
| launch_006 | launch | go | go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 34.6s |
| launch_007 | launch | no_go | go | ✗ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 33.1s |
| launch_008 | launch | needs_more_data | go | ✗ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 33.6s |
| launch_009 | launch | go | go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 35.0s |
| launch_010 | launch | no_go | go | ✗ | 1.00 | review_qa, competitor_search, price_history | 26.3s |
| returns_001 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 18.6s |
| returns_002 | returns | go | no_go | ✗ | 1.00 | review_qa, predict_return_risk | 18.0s |
| returns_003 | returns | go | go | ✓ | 0.67 | review_qa | 13.4s |
| returns_004 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 17.8s |
| returns_005 | returns | go | go | ✓ | 0.80 | predict_return_risk, review_qa | 18.2s |
| returns_006 | returns | go | no_go | ✗ | 0.67 | review_qa | 14.8s |
| returns_007 | returns | go | go | ✓ | 0.50 | predict_return_risk | 12.4s |
| returns_008 | returns | needs_more_data | go | ✗ | 1.00 | predict_return_risk, review_qa | 18.8s |
| returns_009 | returns | go | go | ✓ | 0.67 | review_qa, predict_return_risk | 18.3s |
| returns_010 | returns | go | go | ✓ | 1.00 | review_qa, predict_return_risk | 18.5s |
| improve_001 | improve | go | go | ✓ | 0.80 | review_qa, competitor_search, price_history | 26.6s |
| improve_002 | improve | go | go | ✓ | 0.67 | competitor_search | 14.4s |
| improve_003 | improve | go | go | ✓ | 0.67 | review_qa | 14.1s |
| improve_004 | improve | go | go | ✓ | 0.80 | competitor_search, price_history | 23.0s |
| improve_005 | improve | go | go | ✓ | 0.67 | review_qa | 14.0s |
| improve_006 | improve | needs_more_data | go | ✗ | 1.00 | competitor_search, price_history, review_qa | 27.8s |
| improve_007 | improve | go | go | ✓ | 0.80 | competitor_search, review_qa | 20.7s |
| improve_008 | improve | go | go | ✓ | 0.00 | competitor_search | 14.0s |
| improve_009 | improve | go | go | ✓ | 1.00 | review_qa, competitor_search, price_history | 26.5s |
| improve_010 | improve | needs_more_data | go | ✗ | 0.67 | review_qa, predict_return_risk, competitor_search | 25.8s |
