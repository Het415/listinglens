"""SSE error frames must be readable and must not leak provider internals.

Context: on 2026-09-17 the chat UI rendered a raw `InstructorRetryException`
containing a 400 body, the whole `failed_generation` payload and the Groq
organisation ID, in a red box, mid-demo. These tests pin the contract that
replaced it.
"""

from __future__ import annotations

import app as app_module

ORG = "org_01kme9gn3keaba7rmhkm29vspj"

RATE_LIMIT = RuntimeError(
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    f"`openai/gpt-oss-120b` in organization `{ORG}` service tier `on_demand` "
    "on tokens per day (TPD): Limit 200000, Used 199130, Requested 1171.', "
    "'code': 'rate_limit_exceeded'}}"
)
TOOL_USE_FAILED = RuntimeError(
    "Error code: 400 - {'error': {'code': 'tool_use_failed', "
    "'failed_generation': '<tool_call>\\n<function=Recommendation>\\n"
    "<parameter=decision>\\nngo\\n</parameter>'}}"
)
MODEL_GONE = RuntimeError(
    "Error code: 404 - {'error': {'code': 'model_not_found'}}"
)
# Groq's 413 carries the rate-limit code too, which is why ordering matters.
TOO_LARGE = RuntimeError(
    "Error code: 413 - {'error': {'message': 'Request too large for model "
    f"`openai/gpt-oss-120b` in organization `{ORG}` service tier `on_demand` "
    "on tokens per minute (TPM): Limit 8000, Requested 12045, please reduce "
    "your message size and try again.', 'type': 'tokens', "
    "'code': 'rate_limit_exceeded'}}"
)


def _msg(e):
    return app_module.user_facing_error(e)["message"]


def test_rate_limit_is_explained_and_marked_retryable():
    out = app_module.user_facing_error(RATE_LIMIT)
    assert out["kind"] == "rate_limited"
    assert "try again" in out["message"].lower()


def test_malformed_output_is_explained_as_transient():
    out = app_module.user_facing_error(TOOL_USE_FAILED)
    assert out["kind"] == "malformed_output"
    assert "format" in out["message"].lower()


def test_oversized_prompt_is_not_reported_as_a_rate_limit():
    """Waiting a minute will not shrink the prompt, so no "try again" copy."""
    out = app_module.user_facing_error(TOO_LARGE)
    assert out["kind"] == "too_large"
    assert "try again" not in out["message"].lower()
    assert "shorter" in out["message"].lower()


def test_decommissioned_model_is_not_presented_as_retryable():
    """Retrying a 404 is pointless; the copy must not suggest it."""
    out = app_module.user_facing_error(MODEL_GONE)
    assert out["kind"] == "model_gone"
    assert "try again" not in out["message"].lower()


def test_unknown_errors_name_the_type_but_not_the_message():
    out = app_module.user_facing_error(ValueError("secret-token-abc123 leaked here"))
    assert out["kind"] == "unknown"
    assert "ValueError" in out["message"]
    assert "secret-token-abc123" not in out["message"]


def test_no_payload_leaks_provider_internals():
    """The regression that motivated all of this."""
    for e in (RATE_LIMIT, TOOL_USE_FAILED, MODEL_GONE, TOO_LARGE):
        message = _msg(e)
        for leak in (ORG, "failed_generation", "<tool_call>", "Error code:",
                     "Used 199130", "openai/gpt-oss-120b"):
            assert leak not in message, f"{leak!r} leaked into a user-facing message"


def test_messages_are_short_enough_to_render_in_a_chat_bubble():
    for e in (RATE_LIMIT, TOOL_USE_FAILED, MODEL_GONE, TOO_LARGE, ValueError("x")):
        assert len(_msg(e)) < 200


def test_payload_shape_is_stable_for_the_frontend():
    out = app_module.user_facing_error(RATE_LIMIT)
    assert set(out) == {"message", "kind"}
    assert all(isinstance(v, str) for v in out.values())


def test_full_detail_still_reaches_the_server_log(capsys):
    """Nothing is lost for debugging — only the browser gets the short form."""
    app_module.user_facing_error(RATE_LIMIT, context="assistant/query copilot")
    logged = capsys.readouterr().out
    assert "assistant/query copilot" in logged
    assert "Used 199130" in logged, "the log must keep what the UI drops"
