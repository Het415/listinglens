# Eval Report — 2026-05-17 — full

- **Variant:** `full`
- **Queries:** 1 (1 success, 0 errors)
- **Agent model:** `meta-llama/llama-4-scout-17b-16e-instruct`
- **Judge model:** `claude-haiku-4-5-20251001 (Anthropic)`

## Summary

| Metric | Value |
|---|---|
| Decision accuracy | 0.0% |
| Trajectory F1 (avg) | 0.857 |
| Trajectory precision (avg) | 1.000 |
| Trajectory recall (avg) | 0.750 |
| First-tool match rate | 0.0% |
| Latency p50 / p95 (s) | 10.4 / 10.4 |
| Error rate | 0.0% |

## Per-query results

| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |
|---|---|---|---|---|---|---|---|
| launch_001 | launch | needs_more_data | go | ✗ | 0.86 | competitor_search, trend_signal, review_qa | 10.4s |
