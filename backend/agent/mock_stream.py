"""Mock SSE event streams for frontend development without burning Groq tokens.

Use the `/agent/query/mock` endpoint in app.py to stream these. The shapes
match exactly what run_agent_streaming() produces, so the frontend code
that consumes events doesn't change between mock and live.
"""
import asyncio
from typing import AsyncIterator


# Single canonical fixture: a returns-style query on the TOZO T10 earbuds.
# The predict_return_risk numbers are what the tool returns for B08XPWDSWW
# since the 2026-09-23 feature fix (audit T-08): the old 77.4% HIGH came from
# scoring every product as a 3.0-star product. Reasoning is stubbed but
# plausible. Delays are tuned so the trace animates believably (~6-8s
# end-to-end, similar to real runs).

_RETURNS_FIXTURE: list[dict] = [
    {"delay_ms": 0,   "event": "started", "data": {
        "asin": "B08XPWDSWW",
        "product_name": "TOZO T10 Bluetooth Earbuds",
        "query": "Why are returns spiking on this product?",
    }},
    {"delay_ms": 200, "event": "node_started", "data": {
        "node": "planner", "label": "Planning research...",
    }},
    {"delay_ms": 700, "event": "plan_ready", "data": {
        "query_type": "returns",
        "plan": ["predict_return_risk", "review_qa"],
    }},
    {"delay_ms": 150, "event": "node_completed", "data": {"node": "planner"}},
    {"delay_ms": 200, "event": "node_started", "data": {
        "node": "executor", "label": "Picking next action...",
    }},
    {"delay_ms": 600, "event": "tool_call", "data": {
        "tool": "predict_return_risk", "args": {},
    }},
    {"delay_ms": 100, "event": "node_completed", "data": {"node": "executor"}},
    {"delay_ms": 400, "event": "tool_result", "data": {
        "tool": "predict_return_risk",
        "result_preview": (
            '{"asin": "B08XPWDSWW", "risk_score": 0.0072, "risk_label": "LOW", '
            '"risk_pct": 0.7, "confidence": 0.9928, '
            '"explanation": "Risk drivers: 31% of reviews are negative; '
            'significant gap between ratings and review sentiment"}'
        ),
    }},
    {"delay_ms": 250, "event": "node_started", "data": {
        "node": "executor", "label": "Picking next action...",
    }},
    {"delay_ms": 800, "event": "tool_call", "data": {
        "tool": "review_qa",
        "args": {"question": "What are the top complaints in 1-star reviews?"},
    }},
    {"delay_ms": 100, "event": "node_completed", "data": {"node": "executor"}},
    {"delay_ms": 1500, "event": "tool_result", "data": {
        "tool": "review_qa",
        "result_preview": (
            '{"answer": "1-star reviews concentrate on three themes: poor '
            'sound quality compared to expectations set by 5-star reviews, '
            "frustration with the company's customer service when products "
            'fail, and skepticism that many 5-star reviews are incentivized. '
            'Customers report quick battery degradation and disconnections.", '
            '"sources": [{"text": "I was fooled by the 5 star reviews...", '
            '"rating": 1, "sentiment": "negative", "score": -0.72}, ...], '
            '"n_sources": 5}'
        ),
    }},
    {"delay_ms": 250, "event": "node_started", "data": {
        "node": "executor", "label": "Picking next action...",
    }},
    {"delay_ms": 600, "event": "executor_thought", "data": {
        "content": (
            "The quantitative return risk is LOW (0.7%) at a 4.26-star average, "
            "so the data does not show a spike; the 1-star reviews still show "
            "what the unhappy minority returns over. That's enough for an "
            "action plan."
        ),
    }},
    {"delay_ms": 100, "event": "node_completed", "data": {"node": "executor"}},
    {"delay_ms": 200, "event": "node_started", "data": {
        "node": "synthesizer", "label": "Synthesizing recommendation...",
    }},
    {"delay_ms": 1200, "event": "recommendation", "data": {
        "decision": "go",
        "confidence": 0.7,
        "summary": (
            "The review data does not point to a returns spike: the return-risk "
            "model scores this product LOW (0.7%) at a real 4.26-star average. "
            "Where customers are unhappy, 1-star reviewers consistently cite "
            "poor sound quality, slow customer-service response, and "
            "perceived dishonesty around review solicitation. Check actual "
            "return records before treating this as a spike."
        ),
        "reasoning_steps": [
            "Pulled quantitative risk: LOW (0.7%); rating_avg=4.26 outweighs pct_negative=0.31 in the model.",
            "Looked at 1-star review themes via review_qa: sound quality, customer service, review skepticism.",
            "Cross-referenced themes with the model's drivers: the complaints are real but come from a minority of reviewers.",
        ],
        "evidence": [
            {"tool": "predict_return_risk", "snippet": "LOW risk 0.7%; 31% negative reviews in the analysed sample; rating-sentiment gap noted", "relevance": 0.9},
            {"tool": "review_qa", "snippet": "1-star reviewers cite poor sound quality and frustration with customer service", "relevance": 0.85},
            {"tool": "review_qa", "snippet": "Skepticism about 5-star review authenticity damages trust", "relevance": 0.75},
        ],
        "risks": [
            "Improving sound quality requires hardware changes — slow to ship.",
            "Customer-service overhaul has operational cost that compounds before returns drop.",
            "If reviews are genuinely incentivized, addressing it could trigger short-term rating drops.",
        ],
        "suggested_next_actions": [
            "Audit current review-solicitation flow; stop any practice that promises rewards for positive ratings.",
            "Add a clear in-box card with a customer-service email; goal: route warranty issues away from public reviews.",
            "Run a sound-quality A/B in the next manufacturing batch; collect tagged reviews to confirm the change moves the needle.",
        ],
    }},
    {"delay_ms": 150, "event": "node_completed", "data": {"node": "synthesizer"}},
    {"delay_ms": 100, "event": "done", "data": {}},
]


async def stream_mock_returns() -> AsyncIterator[dict]:
    """Yields the canonical returns-query fixture with realistic delays."""
    for entry in _RETURNS_FIXTURE:
        await asyncio.sleep(entry["delay_ms"] / 1000)
        yield {"event": entry["event"], "data": entry["data"]}
