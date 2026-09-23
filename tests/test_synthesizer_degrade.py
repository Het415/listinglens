"""The Synthesizer must not lose a completed run to one bad generation.

Context: on 2026-09-17 a production query gathered all four tool results and
the executor wrote a full analysis, then the final structured call 400'd with
`tool_use_failed` and the user got a raw provider stacktrace. Everything
needed to answer was in state. These tests pin the recovery.

No network and no API key — `resilient_call` is patched to raise.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent.nodes import synthesizer as synth


class FakeToolFailure(RuntimeError):
    """Stands in for Groq's 400 tool_use_failed, message and all."""


GROQ_400 = FakeToolFailure(
    "Error code: 400 - {'error': {'code': 'tool_use_failed', 'failed_generation': "
    "'<tool_call>\\n<function=Recommendation>\\n<parameter=decision>\\nngo\\n'}}"
)

ANALYSIS = (
    "**Should you buy the Echo Dot 2nd Gen now or wait?** The 5th Gen is already "
    "on the shelf at $49.99, so there is no pending upgrade to wait for. At $24.99 "
    "the 2nd Gen sits 66.7% above its 90-day low of $14.99, and smart-speaker "
    "demand is falling 17.1% YoY, so no demand shock will push prices down further."
)


def _state(messages):
    return {
        "asin": "B01K8B8YA8",
        "query": "should i buy this or wait for next version?",
        "query_type": "launch",
        "plan": [],
        "tools_called": ["competitor_search", "trend_signal", "price_history"],
        "messages": messages,
    }


@pytest.fixture
def failing_synthesis(monkeypatch):
    """Make the structured call fail the way production did."""
    monkeypatch.setattr(synth, "groq_client", lambda **_: object())

    def _boom(stage, fn):
        raise GROQ_400

    monkeypatch.setattr(synth, "resilient_call", _boom)


def test_degrades_instead_of_raising(failing_synthesis):
    """The node must return a usable result, not propagate the provider error."""
    out = synth.synthesize_node(_state([
        HumanMessage(content="should i buy this or wait?"),
        ToolMessage(content='{"competitors": ["Echo Dot 5th Gen $49.99"]}',
                    name="competitor_search", tool_call_id="1"),
    ]))
    assert out["synthesis_degraded"] is True
    assert out["recommendation"] is not None


def test_degraded_result_is_honest_about_what_it_is(failing_synthesis):
    """decision/confidence are the ABSENCE of an answer, not a hedged one."""
    rec = synth.synthesize_node(_state([
        ToolMessage(content='{"trend": "falling"}', name="trend_signal", tool_call_id="1"),
    ]))["recommendation"]

    assert rec.decision == "needs_more_data"
    assert rec.confidence == 0.0
    assert any("degraded" in r.lower() for r in rec.risks), \
        "the user must be told this is not a model judgement"
    assert rec.evidence_gaps, "must name what is missing"


def test_tool_results_survive_as_evidence(failing_synthesis):
    """The research completed — throwing it away was the original bug."""
    rec = synth.synthesize_node(_state([
        ToolMessage(content='{"competitors": ["A"]}', name="competitor_search", tool_call_id="1"),
        ToolMessage(content='{"trend": "falling", "yoy": -17.1}', name="trend_signal", tool_call_id="2"),
        ToolMessage(content='{"price": 24.99, "low_90d": 14.99}', name="price_history", tool_call_id="3"),
    ]))["recommendation"]

    assert len(rec.evidence) == 3
    assert {e.tool for e in rec.evidence} == {
        "competitor_search", "trend_signal", "price_history"
    }
    # Verbatim, so a reader can act on it without the model.
    assert any("14.99" in e.snippet for e in rec.evidence)


def test_recovers_the_executors_written_analysis(failing_synthesis):
    """The production case: a complete answer existed in an executor message."""
    rec = synth.synthesize_node(_state([
        AIMessage(content=ANALYSIS, name="executor"),
        ToolMessage(content='{"price": 24.99}', name="price_history", tool_call_id="1"),
    ]))["recommendation"]

    assert "5th Gen is already" in rec.summary, \
        "the executor's analysis is a real answer and must reach the user"


def test_ignores_planner_and_degraded_executor_chatter():
    """Only substantive executor prose counts as an analysis."""
    assert synth._executor_analysis([
        AIMessage(content="[Planner] query_type=launch; plan=[...]", name="planner"),
        AIMessage(
            content=(
                "I was unable to issue a further tool call. Synthesize a "
                "recommendation from the evidence gathered so far, and note the "
                "missing step as an evidence gap."
            ),
            name="executor_degraded",
        ),
    ]) == ""


def test_no_evidence_at_all_still_returns_something(failing_synthesis):
    """Worst case: nothing was gathered. Must still not raise."""
    rec = synth.synthesize_node(_state([HumanMessage(content="hi")]))["recommendation"]
    assert rec.evidence == []
    assert "could not complete" in rec.summary


def test_success_path_is_untouched(monkeypatch):
    """The guard must not change a normal run."""
    from backend.agent.schemas import Evidence, Recommendation

    good = Recommendation(
        decision="go", confidence=0.85, summary="Buy it now.",
        evidence=[Evidence(tool="price_history", snippet="$24.99", relevance=0.9)],
    )
    monkeypatch.setattr(synth, "groq_client", lambda **_: object())
    monkeypatch.setattr(synth, "resilient_call", lambda stage, fn: good)

    out = synth.synthesize_node(_state([
        ToolMessage(content="{}", name="price_history", tool_call_id="1"),
    ]))
    assert out["synthesis_degraded"] is False
    assert out["recommendation"] is good
    assert "DEGRADED" not in out["messages"][0].content
