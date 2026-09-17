# Eval Report — 2026-09-17 — full

- **Variant:** `full`
- **Queries:** 30 (29 success, 1 errors)
- **Agent model:** `openai/gpt-oss-120b`
- **Executor model:** `openai/gpt-oss-20b`
- **RAG model:** `qwen/qwen3.8-27b`
- **Judge:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy | 60.0% |
| Trajectory F1 (avg) | 0.773 |
| Trajectory precision (avg) | 0.865 |
| Trajectory recall (avg) | 0.750 |
| First-tool match rate | 55.2% |
| Latency p50 / p95 (s) | 33.1 / 48.6 |
| Error rate | 3.3% |

### LLM-as-judge

| Dimension | Avg score |
|---|---|
| Decision correctness | 0.572 |
| Evidence relevance | 0.545 |
| Anti-hallucination (higher=better) | 0.811 |
| Completeness | 0.876 |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | needs_more_data | ✓ | 1.00 | competitor_search, price_history, trend_signal, review_qa | 35.5s |
| launch_002 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 41.3s |
| launch_003 | launch | needs_more_data | no_go | ✗ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 42.5s |
| launch_004 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | trend_signal, competitor_search, price_history | 36.3s |
| launch_005 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, trend_signal, price_history | 42.7s |
| launch_006 | launch | go | needs_more_data | ✗ | 0.67 | competitor_search, price_history, trend_signal | 32.5s |
| launch_007 | launch | no_go | needs_more_data | ✗ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 46.1s |
| launch_008 | launch | needs_more_data | needs_more_data | ✓ | 0.86 | competitor_search, trend_signal, price_history | 49.0s |
| launch_009 | launch | go | go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 48.1s |
| launch_010 | launch | no_go | no_go | ✓ | 0.86 | competitor_search, price_history, trend_signal, review_qa | 48.0s |
| returns_001 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 31.2s |
| returns_002 | returns | go | needs_more_data | ✗ | 0.67 | review_qa | 44.6s |
| returns_003 | returns | go | needs_more_data | ✗ | 0.67 | review_qa | 19.7s |
| returns_004 | returns | go | go | ✓ | 1.00 | predict_return_risk, review_qa | 17.3s |
| returns_005 | returns | go | ERROR | err | 0.00 | (none) | 17.9s |
| returns_006 | returns | go | go | ✓ | 0.67 | review_qa | 46.1s |
| returns_007 | returns | go | go | ✓ | 0.80 | predict_return_risk, review_qa | 26.6s |
| returns_008 | returns | needs_more_data | go | ✗ | 0.50 | predict_return_risk, trend_signal | 17.0s |
| returns_009 | returns | go | go | ✓ | 0.50 | predict_return_risk, review_qa, competitor_search | 33.7s |
| returns_010 | returns | go | go | ✓ | 0.67 | review_qa | 24.5s |
| improve_001 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 25.4s |
| improve_002 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 14.0s |
| improve_003 | improve | go | go | ✓ | 0.50 | competitor_search, review_qa | 18.5s |
| improve_004 | improve | go | go | ✓ | 0.80 | competitor_search, review_qa | 22.9s |
| improve_005 | improve | go | needs_more_data | ✗ | 0.67 | review_qa | 28.2s |
| improve_006 | improve | needs_more_data | needs_more_data | ✓ | 0.67 | competitor_search, price_history, trend_signal | 47.2s |
| improve_007 | improve | go | go | ✓ | 0.80 | competitor_search, review_qa | 49.0s |
| improve_008 | improve | go | needs_more_data | ✗ | 1.00 | review_qa | 4.5s |
| improve_009 | improve | go | go | ✓ | 1.00 | review_qa, competitor_search, price_history | 26.2s |
| improve_010 | improve | needs_more_data | go | ✗ | 0.67 | trend_signal, competitor_search, price_history | 39.7s |

## Failure modes

- **returns_005**: InstructorRetryException: Error code: 400 - {'error': {'message': 'Failed to parse tool call arguments as JSON', 'type': 'invalid_request_error', 'code': 'tool_use_failed', 'failed_generation': '{"name": "Recommendation", "arguments": {\n  "confidence": 0. nine,\n  "decision": "go",\n  "summary": "Your return rate is high because many buyers are unhappy with the product’s performance and feel misled by the rating, plus there’s frustration with your review solicitation method. Fixing product quality, clarifying expectations, and improving the review process should lower returns.",\n  "reasoning_steps": [\n    "Predict_return_risk flagged a HIGH risk (91.2%) and cited negative reviews and low average rating as drivers.",\n    "Review_qa of 1‑star reviews highlighted customers explicitly stating they are returning the item and criticizing product reliability and review solicitation.",\n    "Both tools point to product dissatisfaction and trust issues as the primary cause of returns.",\n    "Conclude that addressing these pain points will likely reduce the return rate."\n  ],\n  "evidence": [\n    {\n      "tool": "predict_return_risk",\n      "snippet": "\\"Risk drivers: 31% of reviews are negative; average rating is low at 3.0/5; significant gap between ratings and review sentiment\\"",\n      "relevance": 1.0\n    },\n    {\n      "tool": "review_qa",\n      "snippet": "\\"...I’m going to return the product to Amazon and leave up this 1-star review... product’s high star rating is misleading... frustration regarding the company’s review solicitation tactics...\\"",\n      "relevance": 1.0\n    }\n  ],\n  "evidence_gaps": [],\n  "risks": [\n    "If the underlying quality issues require redesign, costs could be significant.",\n    "Changes to review solicitation may affect the volume of positive reviews.",\n    "Other factors like shipping damage may also contribute but were not captured."\n  ],\n  "suggested_next_actions": [\n    "Collect detailed defect data from returned items to pinpoint specific quality problems.",\n    "Improve product testing and quality control processes.",\n    "Update the product listing to set realistic expectations about performance and durability.",\n    "Revise any forced‑review or email solicitation practices to comply with Amazon policies.",\n    "Monitor return rate weekly after implementing changes to measure impact."\n  ]\n}"}'}}
