"""End-to-end graph smoke test with fake LLMs: no key, no network.

Why this exists (audit E-11, E-10): `run_agent` referenced three variables it
never received, so every call raised NameError from 2026-09-20 on. The CLI and
the full-variant eval were dead, and CI stayed green six times, because nothing
ran the graph without a Groq key. This runs both entries through the real
compiled graph on every PR, forks included, with only the LLM calls replaced:

- the planner's and synthesizer's `resilient_call` return canned structured
  output, and their `groq_client` is never built;
- the executor's `resilient_call` scripts which tool to call and when to stop;
- `predict_return_risk` runs for real (offline XGBoost over cached features);
- `review_qa` is stubbed, since the real one needs FAISS plus an LLM.

Same approach as audit/_work/phase3/scripts/agt01_harness.py.
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

import backend.agent.graph as graph
import backend.agent.nodes.executor as executor
import backend.agent.nodes.planner as planner
import backend.agent.nodes.synthesizer as synthesizer
from backend.agent.schemas import AgentOutput, Evidence, Plan, Recommendation
from backend.mcp_server.tools import review_qa as review_qa_tool

ASIN = "B08XPWDSWW"
QUERY = "Why are returns spiking on this product?"

RATE_LIMITED = RuntimeError(
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-20b` on tokens per day (TPD): Limit 200000, Used 199990.', "
    "'code': 'rate_limit_exceeded'}}"
)


def _recommendation() -> Recommendation:
    return Recommendation(
        decision="go",
        confidence=0.8,
        summary="Return risk is low; the unhappy minority cites sound quality.",
        reasoning_steps=["Checked the return-risk model.", "Read the 1-star themes."],
        evidence=[Evidence(tool="predict_return_risk", snippet="LOW risk", relevance=0.9)],
        risks=["Sound complaints could grow."],
        suggested_next_actions=["Tag reviews by complaint theme."],
        evidence_gaps=[],
    )


@pytest.fixture
def fake_llms(monkeypatch):
    """Patch every LLM call site; return a dict the test can steer."""
    control = {"executor_script": ["predict_return_risk", "done"], "executor_calls": 0,
               "executor_error": None, "tool_calls_made": []}

    def planner_call(stage, fn):
        return Plan(query_type="returns", tool_sequence=["predict_return_risk"],
                    rationale="returns question")

    def executor_call(stage, fn):
        control["executor_calls"] += 1
        if control["executor_error"] is not None:
            raise control["executor_error"]
        step = control["executor_script"][min(control["executor_calls"] - 1,
                                              len(control["executor_script"]) - 1)]
        if step == "done":
            return AIMessage(content="I have enough evidence.")
        control["tool_calls_made"].append(step)
        return AIMessage(content="", tool_calls=[
            {"name": step, "args": {}, "id": f"call_{control['executor_calls']}"}])

    def synthesizer_call(stage, fn):
        return _recommendation()

    def no_client():
        raise AssertionError("a Groq client must never be built in this test")

    monkeypatch.setattr(planner, "resilient_call", planner_call)
    monkeypatch.setattr(planner, "groq_client", lambda: None)
    monkeypatch.setattr(executor, "resilient_call", executor_call)
    monkeypatch.setattr(synthesizer, "resilient_call", synthesizer_call)
    monkeypatch.setattr(synthesizer, "groq_client", lambda: None)
    monkeypatch.setattr(review_qa_tool, "review_qa",
                        lambda asin, question: {"answer": "stub", "sources": [], "n_sources": 0})
    # A fresh graph so no test sees another's compiled closures.
    monkeypatch.setattr(graph, "_GRAPH_CACHE", {})
    return control


def _stream(**kwargs) -> list[dict]:
    async def collect():
        return [e async for e in graph.run_agent_streaming(ASIN, QUERY, **kwargs)]
    return asyncio.run(collect())


# ── run_agent (the CLI and eval entry) ────────────────────────────────────────

def test_run_agent_completes_end_to_end(fake_llms):
    out = graph.run_agent(ASIN, QUERY)

    assert isinstance(out, AgentOutput)
    assert out.recommendation.decision == "go"
    assert out.trace.tools_called == ["predict_return_risk"]
    assert out.trace.synthesis_degraded is False
    assert out.trace.executor_degraded is False


def test_run_agent_accepts_the_image_context(fake_llms):
    """The three parameters whose absence was the NameError."""
    out = graph.run_agent(ASIN, QUERY, audit_id="abc123def456",
                          image_urls=["https://example.com/a.jpg"], main_index=0)
    assert out.recommendation is not None


def test_run_agent_rejects_an_unknown_asin(fake_llms):
    with pytest.raises(ValueError, match="not in the supported catalog"):
        graph.run_agent("B000000000", QUERY)


def test_both_entries_build_the_same_initial_state():
    a = graph._initial_state(ASIN, QUERY, "TOZO", audit_id="x", image_urls=None, main_index=1)
    assert a["image_urls"] == [] and a["main_index"] == 1 and a["audit_id"] == "x"
    assert a["messages"][0].content == QUERY


# ── run_agent_streaming (the production entry) ────────────────────────────────

def test_streaming_emits_a_full_trace(fake_llms):
    events = _stream()
    names = [e["event"] for e in events]

    assert names[0] == "started"
    assert "plan_ready" in names
    assert "tool_call" in names and "tool_result" in names
    assert names[-1] == "done"
    rec = next(e["data"] for e in events if e["event"] == "recommendation")
    assert rec["decision"] == "go"
    assert rec["degraded"] is False
    # The real tool ran, on the retrained model: LOW, not the old 77.4% HIGH.
    result = next(e["data"] for e in events if e["event"] == "tool_result")
    assert '"risk_label": "LOW"' in result["result_preview"]


# ── executor degradation is visible (audit E-12) ──────────────────────────────

def test_exhausted_executor_is_flagged_on_the_trace(fake_llms):
    fake_llms["executor_error"] = RATE_LIMITED
    out = graph.run_agent(ASIN, QUERY)

    assert out.trace.executor_degraded is True
    assert out.trace.tools_called == []


def test_exhausted_executor_marks_the_streamed_recommendation_degraded(fake_llms):
    fake_llms["executor_error"] = RATE_LIMITED
    events = _stream()

    rec = next(e["data"] for e in events if e["event"] == "recommendation")
    assert rec["degraded"] is True
    assert rec["executor_degraded"] is True
    assert rec["synthesis_degraded"] is False


def test_a_later_good_turn_does_not_clear_the_flag(fake_llms):
    """Degrade once, then succeed: the run still skipped a step."""
    calls = {"n": 0}
    real = executor.resilient_call

    def flaky(stage, fn):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RATE_LIMITED
        return real(stage, fn)

    # First executor turn degrades; the fixture's script then finishes the run.
    fake_llms["executor_script"] = ["done"]
    executor.resilient_call = flaky
    try:
        out = graph.run_agent(ASIN, QUERY)
    finally:
        executor.resilient_call = real
    assert out.trace.executor_degraded is True
