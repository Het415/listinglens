"""Tests for the model fallback policy in src/llm_config.py.

Scope: pure logic — `resilient_call` is driven with fake callables, so no
GROQ_API_KEY, no network, no LLM. The fallback chain is the app's durability
mechanism (Groq has decommissioned models out from under this project three
times), and its retry policy is exactly the kind of branchy code that is easy
to get subtly wrong and impossible to notice in production.
"""

from __future__ import annotations

import groq
import httpx
import pytest
from instructor.core.exceptions import InstructorRetryException

import src.llm_config as llm_config
from src.llm_config import (
    _failover_reason,
    groq_client,
    is_provider_capacity_error,
    model_chain,
    request_timeout,
    resilient_call,
)

# Real Groq error strings, copied from the failures they came from.
GONE = "Error code: 404 - {'error': {'code': 'model_not_found', 'message': '...'}}"
RATE_LIMITED = "Error code: 429 - {'error': {'code': 'rate_limit_exceeded'}}"
MALFORMED = (
    "Error code: 400 - {'error': {'code': 'tool_use_failed', 'message': "
    "'Failed to parse tool call arguments as JSON'}}"
)


def test_first_model_wins_without_retrying():
    calls = []
    out = resilient_call("agent", lambda m: (calls.append(m), "ok")[1])
    assert out == "ok"
    assert calls == [model_chain("agent")[0]]


def test_decommissioned_model_advances_immediately():
    """A 404 is not stochastic — no point re-running the same model."""
    calls = []

    def fn(model):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError(GONE)
        return "ok"

    assert resilient_call("agent", fn) == "ok"
    assert calls == model_chain("agent")[:2]


def test_rate_limited_model_advances_immediately():
    calls = []

    def fn(model):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError(RATE_LIMITED)
        return "ok"

    assert resilient_call("rag", fn) == "ok"
    assert calls == model_chain("rag")[:2]


def test_malformed_tool_call_retries_same_model_first():
    """The 3.3% eval failure mode. Stochastic, so the cheap fix is a re-run.

    Regression guard for the bug this fix addresses: instructor's own
    `max_retries` never engages here, because a `tool_use_failed` 400 is a
    BadRequestError and instructor only retries parse/validation errors.
    """
    calls = []

    def fn(model):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError(MALFORMED)
        return "ok"

    assert resilient_call("agent", fn) == "ok"
    primary = model_chain("agent")[0]
    assert calls == [primary, primary], "should re-run the SAME model, not fail over"


def test_malformed_tool_call_falls_over_after_one_same_model_retry():
    """One retry per model, then advance — not an unbounded loop on model #1."""
    calls = []

    def fn(model):
        calls.append(model)
        if len(calls) <= 2:
            raise RuntimeError(MALFORMED)
        return "ok"

    assert resilient_call("agent", fn) == "ok"
    a, b, c = model_chain("agent")[:3]
    assert calls == [a, a, b]


def test_persistent_malformed_tool_calls_are_bounded_and_reraise():
    """Worst case: every model, each retried once. Then the real error surfaces."""
    calls = []

    def fn(model):
        calls.append(model)
        raise RuntimeError(MALFORMED)

    with pytest.raises(RuntimeError, match="tool_use_failed"):
        resilient_call("agent", fn)

    chain = model_chain("agent")
    assert len(calls) == 2 * len(chain)
    assert calls == [m for m in chain for _ in range(2)]


def test_unrelated_error_propagates_untouched():
    """A bad API key or a bug in our request must not burn the whole chain."""
    calls = []

    def fn(model):
        calls.append(model)
        raise RuntimeError("Error code: 401 - {'error': {'code': 'invalid_api_key'}}")

    with pytest.raises(RuntimeError, match="invalid_api_key"):
        resilient_call("agent", fn)
    assert len(calls) == 1


def test_llm_no_failover_opts_out_of_the_chain():
    """The executor node's escape hatch — it runs its own retry policy.

    Its exception embeds the original Groq text, so it *would* match the
    malformed-tool-call signature; the marker attribute is what stops
    resilient_call from re-retrying work the caller already retried.
    """

    class AlreadyHandled(RuntimeError):
        llm_no_failover = True

    calls = []

    def fn(model):
        calls.append(model)
        raise AlreadyHandled(MALFORMED)

    with pytest.raises(AlreadyHandled):
        resilient_call("executor", fn)
    assert len(calls) == 1, "must not walk the chain for an opted-out error"


# ── timeouts, dropped connections and 5xx (audit E-19, CMD-02) ────────────────
# Real groq SDK exceptions, matched by type. Their messages are generic
# ("Request timed out.", "Connection error."), which is why no substring
# signature ever caught them: CMD-02 returned None for all three.

_REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _status_error(cls, code: int, message: str):
    return cls(message, response=httpx.Response(code, request=_REQ), body=None)


def _instructor_wrapped(err: Exception) -> InstructorRetryException:
    """How the planner, synthesizer and Brief see a provider error: instructor
    re-raises it as `InstructorRetryException(str(err)) from err`."""
    try:
        raise InstructorRetryException(str(err), n_attempts=1, total_usage=0) from err
    except InstructorRetryException as wrapped:
        return wrapped


UNAVAILABLE = {
    "timeout": groq.APITimeoutError(request=_REQ),
    "connection": groq.APIConnectionError(request=_REQ),
    "5xx": _status_error(groq.InternalServerError, 503, "Service Unavailable"),
}
AUTH_401 = _status_error(groq.AuthenticationError, 401, "Invalid API Key")


@pytest.mark.parametrize("kind", sorted(UNAVAILABLE))
@pytest.mark.parametrize("wrap", [False, True], ids=["bare", "instructor-wrapped"])
def test_unavailable_provider_is_a_failover_signature(kind, wrap):
    err = UNAVAILABLE[kind]
    if wrap:
        err = _instructor_wrapped(err)
    assert _failover_reason(err) is not None
    assert is_provider_capacity_error(err) is True


@pytest.mark.parametrize("wrap", [False, True], ids=["bare", "instructor-wrapped"])
def test_a_401_is_still_not_a_failover_signature(wrap):
    err = _instructor_wrapped(AUTH_401) if wrap else AUTH_401
    assert _failover_reason(err) is None
    assert is_provider_capacity_error(err) is False


@pytest.mark.parametrize("kind", sorted(UNAVAILABLE))
def test_unavailable_model_advances_to_the_next(kind):
    calls = []

    def fn(model):
        calls.append(model)
        if len(calls) == 1:
            raise UNAVAILABLE[kind]
        return "ok"

    assert resilient_call("executor", fn) == "ok"
    assert calls == model_chain("executor")[:2]


def test_a_401_does_not_walk_the_chain():
    calls = []

    def fn(model):
        calls.append(model)
        raise AUTH_401

    with pytest.raises(groq.AuthenticationError):
        resilient_call("agent", fn)
    assert len(calls) == 1


# ── the stage deadline bounds a hung provider (Step 1b) ───────────────────────
# A fake clock stands in for time: each attempt advances it by what a hung Groq
# would cost, which is the read timeout once per SDK try plus backoff, and
# `resilient_call` reads it through `llm_config._now`.
#   executor / RAG ChatGroq, max_retries=1: 2 x 20 s + 0.5 s = 40.5 s
#   instructor clients, SDK default retries 2: 3 x 20 s + 1.5 s = 61.5 s

EXECUTOR_HANG_S = 40.5
INSTRUCTOR_HANG_S = 61.5


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(llm_config, "_now", c)
    monkeypatch.delenv("LLM_STAGE_DEADLINE_S", raising=False)
    return c


def _costs(clock, calls, seconds, err):
    """An `fn` that spends `seconds` of fake time on each model, then raises."""
    def fn(model):
        calls.append(model)
        clock.t += seconds
        raise err
    return fn


def test_a_hung_chain_stops_at_the_stage_deadline(clock):
    """40.5 s < 45 s, so the second model is tried; 81 s is past it, so not the third."""
    calls = []
    with pytest.raises(groq.APITimeoutError):
        resilient_call("executor", _costs(clock, calls, EXECUTOR_HANG_S, UNAVAILABLE["timeout"]))
    assert calls == model_chain("executor")[:2]
    assert clock.t == 2 * EXECUTOR_HANG_S


def test_an_attempt_that_outlasts_the_deadline_does_not_fail_over(clock):
    calls = []
    with pytest.raises(groq.APITimeoutError):
        resilient_call("agent", _costs(clock, calls, INSTRUCTOR_HANG_S, UNAVAILABLE["timeout"]))
    assert calls == model_chain("agent")[:1]


@pytest.mark.parametrize("kind", sorted(UNAVAILABLE))
def test_fast_unavailable_errors_still_walk_the_whole_chain(clock, kind):
    """A refused connection or a quick 503 costs seconds, so all three are tried."""
    calls = []
    with pytest.raises(type(UNAVAILABLE[kind])):
        resilient_call("rag", _costs(clock, calls, 1.5, UNAVAILABLE[kind]))
    assert calls == model_chain("rag")


@pytest.mark.parametrize("text", [
    GONE, RATE_LIMITED, "Error code: 413 - {'error': {'message': 'Request too large'}}",
], ids=["404", "429", "413"])
def test_the_deadline_leaves_the_older_failovers_alone(clock, text):
    """100 s per attempt is far past the deadline; these advanced before and still do."""
    calls = []
    with pytest.raises(RuntimeError):
        resilient_call("agent", _costs(clock, calls, 100, RuntimeError(text)))
    assert calls == model_chain("agent")


def test_malformed_tool_calls_ignore_the_deadline(clock):
    calls = []
    with pytest.raises(RuntimeError, match="tool_use_failed"):
        resilient_call("agent", _costs(clock, calls, 100, RuntimeError(MALFORMED)))
    assert len(calls) == 2 * len(model_chain("agent"))


def test_the_deadline_is_env_configurable(clock, monkeypatch):
    monkeypatch.setenv("LLM_STAGE_DEADLINE_S", "200")
    calls = []
    with pytest.raises(groq.APITimeoutError):
        resilient_call("agent", _costs(clock, calls, INSTRUCTOR_HANG_S, UNAVAILABLE["timeout"]))
    assert calls == model_chain("agent")


# ── every production client gets the shared read timeout (Step 1b) ────────────

@pytest.fixture
def default_timeout(monkeypatch):
    monkeypatch.delenv("LLM_REQUEST_TIMEOUT_S", raising=False)


def test_the_shared_timeout_is_20s_read_and_5s_connect(default_timeout):
    t = request_timeout()
    assert (t.read, t.connect) == (20.0, 5.0)


def test_the_request_timeout_is_env_configurable(monkeypatch):
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_S", "60")
    assert request_timeout().read == 60.0


def test_the_instructor_client_uses_it_and_keeps_its_sdk_retries(default_timeout, monkeypatch):
    """The default profile: the planner and intent. The synthesizer and the Brief
    use `groq_client(long_output=True)` (tests/test_long_output_timeout.py)."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_dummy_never_sent")
    inner = groq_client().client
    assert (inner.timeout.read, inner.timeout.connect) == (20.0, 5.0)
    # Unchanged, so the SDK's 429 retry-after handling is unchanged too.
    assert inner.max_retries == 2


class _RecordingChatGroq:
    built: list[dict] = []

    def __init__(self, **kwargs):
        type(self).built.append(kwargs)

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        return AIMessage(content="done")


def test_the_executor_and_rag_clients_use_it(default_timeout, monkeypatch):
    import langchain_groq
    from langchain_core.messages import HumanMessage

    import backend.agent.nodes.executor as executor
    from src import rag_chatbot

    _RecordingChatGroq.built = []
    monkeypatch.setattr(executor, "ChatGroq", _RecordingChatGroq)
    monkeypatch.setattr(langchain_groq, "ChatGroq", _RecordingChatGroq)

    executor.make_executor_node(tools=[])({
        "asin": "B08XPWDSWW", "product_name": "TOZO", "plan": [], "tools_called": [],
        "messages": [HumanMessage(content="q")], "replans_done": 0, "iterations": 0,
    })
    rag_chatbot.build_rag_chain(vectorstore=None)

    assert len(_RecordingChatGroq.built) == 2
    for kwargs in _RecordingChatGroq.built:
        assert kwargs["request_timeout"].read == 20.0
        assert kwargs["max_retries"] == 1


# ── a request we could not send is our bug, not an outage (PR #9 CI) ──────────

def _refused_to_send() -> groq.APIConnectionError:
    """What the SDK raises for an empty GROQ_API_KEY: h11 rejects the header
    `Authorization: Bearer ` before any connection is made, and the SDK
    re-raises it as `APIConnectionError(...) from err` (_base_client.py)."""
    try:
        try:
            raise httpx.LocalProtocolError("Illegal header value b'Bearer '")
        except httpx.LocalProtocolError as err:
            raise groq.APIConnectionError(request=_REQ) from err
    except groq.APIConnectionError as e:
        return e


def _server_broke_protocol() -> groq.APIConnectionError:
    try:
        try:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        except httpx.RemoteProtocolError as err:
            raise groq.APIConnectionError(request=_REQ) from err
    except groq.APIConnectionError as e:
        return e


@pytest.mark.parametrize("wrap", [False, True], ids=["bare", "instructor-wrapped"])
def test_an_unsendable_request_is_not_a_failover_signature(wrap):
    err = _instructor_wrapped(_refused_to_send()) if wrap else _refused_to_send()
    assert _failover_reason(err) is None
    assert is_provider_capacity_error(err) is False


def test_an_empty_key_does_not_walk_the_chain():
    calls = []

    def fn(model):
        calls.append(model)
        raise _refused_to_send()

    with pytest.raises(groq.APIConnectionError):
        resilient_call("agent", fn)
    assert len(calls) == 1


def test_a_server_side_protocol_error_is_still_unavailable():
    err = _server_broke_protocol()
    assert _failover_reason(err) is not None
    assert is_provider_capacity_error(err) is True
