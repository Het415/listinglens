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

import groq
import httpx
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

# Real SDK exceptions for a provider that is down rather than refusing us
# (audit E-19). Before T-04 these re-raised here and aborted the run.
_REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
TIMEOUT = groq.APITimeoutError(request=_REQ)
CONNECTION = groq.APIConnectionError(request=_REQ)
SERVER_5XX = groq.InternalServerError(
    "Service Unavailable", response=httpx.Response(503, request=_REQ), body=None)
AUTH_401 = groq.AuthenticationError(
    "Invalid API Key", response=httpx.Response(401, request=_REQ), body=None)


def _empty_key() -> groq.APIConnectionError:
    # An empty GROQ_API_KEY: h11 refuses the header `Bearer ` before sending,
    # and the SDK re-raises that as a connection error (seen in CI, PR #9).
    try:
        try:
            raise httpx.LocalProtocolError("Illegal header value b'Bearer '")
        except httpx.LocalProtocolError as err:
            raise groq.APIConnectionError(request=_REQ) from err
    except groq.APIConnectionError as e:
        return e


EMPTY_KEY = _empty_key()


# ── the classifier ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("err", [TPD, OTPM, GONE, TIMEOUT, CONNECTION, SERVER_5XX])
def test_capacity_errors_are_recognised(err):
    assert is_provider_capacity_error(err) is True


@pytest.mark.parametrize("err", [AUTH, AUTH_401, EMPTY_KEY, BUG])
def test_our_own_faults_are_not_capacity_errors(err):
    assert is_provider_capacity_error(err) is False


# ── the executor branch ───────────────────────────────────────────────────────

def _invoke(monkeypatch, err):
    """Drive _invoke_with_retry with resilient_call raising `err`."""
    def _boom(stage, fn):
        raise err
    monkeypatch.setattr(ex, "resilient_call", _boom)
    return ex._invoke_with_retry(bind_for=lambda m: None, messages=[])


@pytest.mark.parametrize("err,label", [
    (TPD, "TPD"), (OTPM, "OTPM"), (GONE, "decommissioned"),
    (TIMEOUT, "timeout"), (CONNECTION, "connection"), (SERVER_5XX, "5xx"),
])
def test_exhausted_chain_degrades_so_the_graph_can_continue(monkeypatch, err, label):
    """The regression guard for improve_006/008/010."""
    msg = _invoke(monkeypatch, err)

    assert isinstance(msg, AIMessage)
    assert msg.name == "executor_degraded"
    # The graph routes on "no tool_calls" -> Synthesizer. Nothing to raise.
    assert not getattr(msg, "tool_calls", None)
    # The cause is preserved for the trace rather than discarded.
    assert msg.additional_kwargs.get("tool_call_error")


@pytest.mark.parametrize("err", [AUTH, AUTH_401, EMPTY_KEY, BUG])
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


# ── a hung provider stops at the stage deadline, then degrades (Step 1b) ──────

def test_a_hung_chain_stops_at_the_deadline_and_the_executor_degrades(monkeypatch):
    """The real `resilient_call`, a fake clock, and a ChatGroq that never answers.

    Each attempt costs what a hung Groq would with the shared 20 s read timeout
    and `max_retries=1`: 2 x 20 s + 0.5 s backoff. The first model fails at
    40.5 s, inside the 45 s deadline, so the second is tried; it fails at 81 s,
    past it, so the third is not, and the executor hands off to the Synthesizer.
    """
    from langchain_core.messages import HumanMessage

    import src.llm_config as llm_config
    from src.llm_config import model_chain

    clock = {"t": 0.0}
    monkeypatch.setattr(llm_config, "_now", lambda: clock["t"])
    monkeypatch.delenv("LLM_STAGE_DEADLINE_S", raising=False)
    tried = []

    class HungChatGroq:
        def __init__(self, **kwargs):
            self.model = kwargs["model"]

        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, messages):
            tried.append(self.model)
            clock["t"] += 40.5
            raise TIMEOUT

    monkeypatch.setattr(ex, "ChatGroq", HungChatGroq)

    update = ex.make_executor_node(tools=[])({
        "asin": "B08XPWDSWW", "product_name": "TOZO", "plan": ["review_qa"],
        "tools_called": [], "messages": [HumanMessage(content="q")],
        "replans_done": 0, "iterations": 0,
    })

    assert tried == model_chain("executor")[:2]
    assert clock["t"] == 81.0
    assert update["executor_degraded"] is True
    assert update["messages"][0].name == "executor_degraded"
    assert not update["messages"][0].tool_calls
