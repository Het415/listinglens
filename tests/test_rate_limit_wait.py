"""A short per-minute 429 is waited out on the same model, not failed over.

Measured 2026-10-05, 3 back-to-back agent questions with HTTP logging: both
executor failovers were gpt-oss-20b 429ing, the groq SDK sleeping exactly the
5 s its `retry-after` header said, and the retry 429ing again at once. The next
model, gpt-oss-safeguard-20b, allows 2,000 tokens a minute on the free tier, so
the failover was usually "request too large" there. Offline: errors carry
Groq's real message text, and `_sleep` is recorded instead of slept.
"""

from __future__ import annotations

import pytest

import src.llm_config as llm_config
from src.llm_config import model_chain, resilient_call, short_rate_limit_wait

ORG = "in organization `org_01kme9gn3keaba7rmhkm29vspj` service tier `on_demand` "


def tpm(wait: str = "2.7225s", model: str = "openai/gpt-oss-20b") -> RuntimeError:
    return RuntimeError(
        f"Error code: 429 - {{'error': {{'message': 'Rate limit reached for model `{model}` {ORG}"
        f"on tokens per minute (TPM): Limit 8000, Used 5678, Requested 2685. "
        f"Please try again in {wait}. Need more tokens?', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}}}")


TPD = RuntimeError(
    f"Error code: 429 - {{'error': {{'message': 'Rate limit reached for model `openai/gpt-oss-20b` {ORG}"
    "on tokens per day (TPD): Limit 200000, Used 199130, Requested 2685. Please try again in 7m26.4s.', "
    "'code': 'rate_limit_exceeded'}}")
TOO_LARGE = RuntimeError(
    f"Error code: 413 - {{'error': {{'message': 'Request too large for model `openai/gpt-oss-safeguard-20b` "
    f"{ORG}on tokens per minute (TPM): Limit 2000, Requested 3212, please reduce your message size and "
    "try again.', 'code': 'rate_limit_exceeded'}}")
# What instructor raises around the SDK's error on the planner and synthesizer.
INSTRUCTOR_WRAPPED = RuntimeError(
    "Max retries exceeded. Total attempts: 1, Last error: " + str(tpm("3.915s", "openai/gpt-oss-120b")))


# ── reading the wait ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("err,expected", [
    (tpm("2.7225s"), 2.7225),
    (tpm("450ms"), 0.45),
    (INSTRUCTOR_WRAPPED, 3.915),
    (RuntimeError("Rate limit reached ... on requests per minute (RPM): Limit 30. Please try again in 1.2s."), 1.2),
])
def test_a_short_per_minute_limit_gives_its_wait(err, expected):
    assert short_rate_limit_wait(err) == pytest.approx(expected)


@pytest.mark.parametrize("err", [
    TPD,                       # per day: minutes or hours
    TOO_LARGE,                 # no wait makes it fit this model
    tpm("28.5s"),              # over the cap: fail over, as before
    tpm("1m3s"),
    RuntimeError("Error code: 404 - {'error': {'code': 'model_not_found'}}"),
])
def test_anything_else_is_not_waited_for(err):
    assert short_rate_limit_wait(err) is None


def test_the_log_message_drops_the_org_id():
    msg = llm_config._provider_message(tpm())
    assert "org_01" not in msg and "service tier" not in msg
    assert msg.startswith("Rate limit reached for model `openai/gpt-oss-20b` on tokens per minute (TPM)")
    assert "try again in 2.7225s" in msg   # the part worth logging survives the cap


# ── the chain ─────────────────────────────────────────────────────────────────

@pytest.fixture
def chain(monkeypatch):
    monkeypatch.delenv("EXECUTOR_MODEL", raising=False)
    slept: list[float] = []
    monkeypatch.setattr(llm_config, "_sleep", slept.append)
    return model_chain("executor"), slept


def scripted(*outcomes):
    """fn(model) that raises or returns each outcome in turn, recording models."""
    tried = []
    queue = list(outcomes)

    def fn(model):
        tried.append(model)
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
    return fn, tried


def test_the_measured_case_waits_and_stays_on_the_same_model(chain):
    models, slept = chain
    fn, tried = scripted(tpm("0.3s"), "ok")

    assert resilient_call("executor", fn) == "ok"
    assert tried == [models[0], models[0]]
    assert slept == [pytest.approx(0.8)]          # the wait plus the 0.5 s margin


def test_it_waits_once_per_model_then_fails_over(chain):
    models, slept = chain
    fn, tried = scripted(tpm(), tpm(), "ok")

    assert resilient_call("executor", fn) == "ok"
    assert tried == [models[0], models[0], models[1]]
    assert len(slept) == 1


@pytest.mark.parametrize("err", [TPD, TOO_LARGE, tpm("28.5s")])
def test_a_long_or_unfittable_limit_fails_over_at_once(chain, err):
    models, slept = chain
    fn, tried = scripted(err, "ok")

    assert resilient_call("executor", fn) == "ok"
    assert tried == [models[0], models[1]]
    assert slept == []


def test_the_next_model_gets_its_own_wait(chain):
    models, slept = chain
    fn, tried = scripted(tpm(), tpm(), tpm(), "ok")

    assert resilient_call("executor", fn) == "ok"
    assert tried == [models[0], models[0], models[1], models[1]]
    assert len(slept) == 2


def test_the_last_model_still_raises_after_its_wait(chain):
    models, slept = chain
    fn, tried = scripted(*[tpm()] * (2 * len(models)))

    with pytest.raises(RuntimeError, match="tokens per minute"):
        resilient_call("executor", fn)
    assert tried == [m for m in models for _ in range(2)]
    assert len(slept) == len(models)


def test_the_instructor_wrapped_error_is_waited_for_too(chain):
    models, slept = chain
    fn, tried = scripted(INSTRUCTOR_WRAPPED, "ok")

    assert resilient_call("executor", fn) == "ok"
    assert tried == [models[0], models[0]] and slept == [pytest.approx(4.415)]
