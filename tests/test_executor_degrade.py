"""The Executor must not lose a run when its whole model chain is exhausted.

Measured on the 2026-09-17 judged run: improve_006, improve_008 and
improve_010 all died in the Executor with tools_called == [], because a
rate-limit-exhausted chain hit a bare `raise`. The run never reached the
Synthesizer, so the Synthesizer's own fallback could not help.

The line it must NOT cross: an auth failure or a bug in the request still
raises. Degrading those would turn a total outage into a stream of plausible
"partial answers" nobody investigates.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from backend.agent.nodes import executor as ex
from src.llm_config import is_provider_capacity_error

TPD = RuntimeError(
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-20b` ... on tokens per day (TPD): Limit 200000, "
    "Used 199130.', 'code': 'rate_limit_exceeded'}}"
)
OTPM = RuntimeError(
    "Error code: 429 - {'error': {'message': 'Request too large for model "
    "`qwen/qwen3.8-27b` ... on output tokens per minute (OTPM): Limit 1000.', "
    "'code': 'rate_limit_exceeded'}}"
)
GONE = RuntimeError("Error code: 404 - {'error': {'code': 'model_not_found'}}")
AUTH = RuntimeError("Error code: 401 - {'error': {'code': 'invalid_api_key'}}")
BUG = TypeError("unsupported operand type(s)")


# ── the classifier ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("err", [TPD, OTPM, GONE])
def test_capacity_errors_are_recognised(err):
    assert is_provider_capacity_error(err) is True


@pytest.mark.parametrize("err", [AUTH, BUG])
def test_our_own_faults_are_not_capacity_errors(err):
    assert is_provider_capacity_error(err) is False


# ── the executor branch ───────────────────────────────────────────────────────

def _invoke(monkeypatch, err):
    """Drive _invoke_with_retry with resilient_call raising `err`."""
    def _boom(stage, fn):
        raise err
    monkeypatch.setattr(ex, "resilient_call", _boom)
    return ex._invoke_with_retry(bind_for=lambda m: None, messages=[])


@pytest.mark.parametrize("err,label", [(TPD, "TPD"), (OTPM, "OTPM"), (GONE, "decommissioned")])
def test_exhausted_chain_degrades_so_the_graph_can_continue(monkeypatch, err, label):
    """The regression guard for improve_006/008/010."""
    msg = _invoke(monkeypatch, err)

    assert isinstance(msg, AIMessage)
    assert msg.name == "executor_degraded"
    # The graph routes on "no tool_calls" -> Synthesizer. Nothing to raise.
    assert not getattr(msg, "tool_calls", None)
    # The cause is preserved for the trace rather than discarded.
    assert msg.additional_kwargs.get("tool_call_error")


@pytest.mark.parametrize("err", [AUTH, BUG])
def test_auth_failures_and_bugs_still_raise(monkeypatch, err):
    """Masking these would hide a total outage behind partial answers."""
    with pytest.raises(type(err)):
        _invoke(monkeypatch, err)


def test_malformed_tool_calls_still_degrade(monkeypatch):
    """Pre-existing behaviour must be unchanged by the new branch."""
    def _boom(stage, fn):
        raise ex._MalformedToolCalls("tool_use_failed on every model")
    monkeypatch.setattr(ex, "resilient_call", _boom)

    msg = ex._invoke_with_retry(bind_for=lambda m: None, messages=[])
    assert msg.name == "executor_degraded"


def test_success_path_is_untouched(monkeypatch):
    good = AIMessage(content="", tool_calls=[
        {"name": "review_qa", "args": {"question": "q"}, "id": "1"},
    ])
    monkeypatch.setattr(ex, "resilient_call", lambda stage, fn: good)

    assert ex._invoke_with_retry(bind_for=lambda m: None, messages=[]) is good
