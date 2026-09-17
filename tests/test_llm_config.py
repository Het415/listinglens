"""Tests for the model fallback policy in src/llm_config.py.

Scope: pure logic — `resilient_call` is driven with fake callables, so no
GROQ_API_KEY, no network, no LLM. The fallback chain is the app's durability
mechanism (Groq has decommissioned models out from under this project three
times), and its retry policy is exactly the kind of branchy code that is easy
to get subtly wrong and impossible to notice in production.
"""

from __future__ import annotations

import pytest

from src.llm_config import model_chain, resilient_call

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

