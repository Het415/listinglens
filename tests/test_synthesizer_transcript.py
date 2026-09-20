"""The Synthesizer must actually see the evidence retrieval found.

A 1500-char cap on each tool result silently deleted most of every `review_qa`
payload. Measured on B08XPWDSWW: the serialized output is 2239 chars as
`{answer, sources, n_sources}`, so `answer` (963) came first and the cut landed
739 chars inside `sources` (1235, 5 entries) — only 2 of 5 retrieved snippets
even started. That is the mechanism behind `evidence_relevance` sitting at
~0.545 while completeness stayed ~0.87.

Pure string assembly, so these run with no network, no API key and no LLM.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent.nodes.synthesizer import _TOOL_RESULT_CHARS, _build_transcript


def _review_qa_payload(n_sources: int = 5, snippet_chars: int = 200) -> str:
    """Mirrors ReviewQAOutput's real shape, field order included.

    Field order is load-bearing: LangGraph's ToolNode serializes with
    json.dumps, which preserves it, so `answer` occupies the first ~960 chars
    and any cut below the total lands inside `sources`.
    """
    return json.dumps({
        "answer": "Customers return this mainly for battery and connectivity faults. " * 14,
        "sources": [
            {"text": f"SOURCE_{i}_" + "x" * snippet_chars, "rating": 1,
             "sentiment": "negative", "score": -0.8}
            for i in range(n_sources)
        ],
        "n_sources": n_sources,
    })


def _transcript(payload: str) -> str:
    return _build_transcript(
        messages=[
            HumanMessage(content="Why are returns spiking?"),
            AIMessage(content="", name="executor"),
            ToolMessage(content=payload, name="review_qa", tool_call_id="1"),
        ],
        query="Why are returns spiking?",
        query_type="returns",
        plan=[],
    )


def test_a_realistic_review_qa_payload_exceeds_the_old_cap():
    """Guard the premise: if this stops being true the bug is gone anyway."""
    assert len(_review_qa_payload()) > 1500


def test_every_retrieved_snippet_survives_into_the_transcript():
    """The regression this fix exists for — 3 of 5 used to be dropped."""
    text = _transcript(_review_qa_payload(n_sources=5))
    for i in range(5):
        assert f"SOURCE_{i}_" in text, f"source {i} was truncated away"
    assert "[truncated]" not in text


def test_the_old_cap_would_have_dropped_most_of_them():
    """Demonstrates the failure directly, so the test documents the bug."""
    payload = _review_qa_payload(n_sources=5)
    survived = sum(1 for i in range(5) if f"SOURCE_{i}_" in payload[:1500])
    assert survived < 5, "expected the old 1500-char cap to lose snippets"


def test_truncation_still_applies_to_a_genuinely_huge_payload():
    """Raising the cap must not mean removing it — the transcript is a prompt."""
    text = _transcript(json.dumps({"blob": "y" * 20_000}))
    assert "[truncated]" in text
    assert len(text) < 20_000


def test_cap_clears_the_measured_worst_case_with_headroom():
    """2239 measured; sources are pre-truncated upstream so it cannot grow far."""
    assert _TOOL_RESULT_CHARS >= 2500


def test_other_tools_were_never_affected():
    """Only review_qa exceeded the old cap; the rest are 252-1197 chars."""
    for name, size in (("competitor_search", 1197), ("price_history", 949),
                       ("trend_signal", 439), ("predict_return_risk", 252)):
        payload = json.dumps({"pad": "z" * (size - 12)})
        text = _build_transcript(
            messages=[ToolMessage(content=payload, name=name, tool_call_id="1")],
            query="q", query_type="returns", plan=[],
        )
        assert "[truncated]" not in text, f"{name} should never have been truncated"
