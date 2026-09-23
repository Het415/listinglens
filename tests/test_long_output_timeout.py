"""The synthesizer and the Brief get a read timeout their answers fit in.

`fce3757b` gave every production client one 20 s read timeout. The synthesizer
and the Executive Brief run gpt-oss-120b at medium reasoning with no
max_tokens and write a long structured answer, so a healthy call can take
20-40 s. Under 20 s it timed out on every SDK try (3 x 20 s + 1.5 s = 61.5 s),
was past the 45 s stage deadline, and came back degraded every time.

Now they use `groq_client(long_output=True)`: a 45 s read timeout and 1 SDK
retry. Everything else stays on 20 s. No key, no network: the Groq SDK is
simulated on a fake clock, each attempt either finishing within the client's
read timeout or timing out once per SDK try with the SDK's backoff.
"""

from __future__ import annotations

import groq
import httpx
import instructor
import pytest
from langchain_core.messages import HumanMessage

import backend.agent.nodes.planner as planner
import backend.agent.nodes.synthesizer as synthesizer
import src.llm_config as llm_config
from backend.agent.schemas import Evidence, Recommendation
from src.llm_config import groq_client, model_chain, request_timeout

_REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
_SDK_DEFAULT_RETRIES = 2     # groq._constants.DEFAULT_MAX_RETRIES


def _recommendation() -> Recommendation:
    return Recommendation(
        decision="go", confidence=0.8, summary="A real, model-written answer.",
        reasoning_steps=["Read the evidence."],
        evidence=[Evidence(tool="predict_return_risk", snippet="LOW", relevance=0.9)],
        risks=["None found."], suggested_next_actions=["Ship it."], evidence_gaps=[],
    )


@pytest.fixture(autouse=True)
def default_timeouts(monkeypatch):
    for var in ("LLM_REQUEST_TIMEOUT_S", "LLM_AGENT_REQUEST_TIMEOUT_S", "LLM_STAGE_DEADLINE_S"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_dummy_never_sent")


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class SimulatedSDK:
    """Stands in for `groq.Groq` plus `instructor.from_groq`.

    Records how each client was built. `generation_s` is how long the model
    takes to answer; None means it never answers.
    """

    def __init__(self, monkeypatch, clock: FakeClock | None = None, generation_s: float | None = 1.0):
        self.clock = clock or FakeClock()
        self.generation_s = generation_s
        self.built: list[dict] = []
        self.tried: list[str] = []
        sdk = self

        class Groq:
            def __init__(self, api_key=None, timeout=None, max_retries=_SDK_DEFAULT_RETRIES):
                self.timeout, self.max_retries = timeout, max_retries
                sdk.built.append({"read": timeout.read, "connect": timeout.connect,
                                  "max_retries": max_retries})

        class Completions:
            def __init__(self, client):
                self.client = client

            def create(self, *, model, response_model, **_):
                if response_model is not Recommendation:
                    # Only the client's construction matters for other callers;
                    # the planner takes its fallback plan on this.
                    raise RuntimeError(f"simulated SDK only answers Recommendation, not {response_model}")
                sdk.tried.append(model)
                read, tries = self.client.timeout.read, 1 + self.client.max_retries
                for n in range(tries):
                    if sdk.generation_s is not None and sdk.generation_s <= read:
                        sdk.clock.t += sdk.generation_s
                        return _recommendation()
                    sdk.clock.t += read
                    if n < tries - 1:
                        sdk.clock.t += min(0.5 * 2 ** n, 8.0)   # the SDK's backoff, upper bound
                raise groq.APITimeoutError(request=_REQ)

        class Instructor:
            def __init__(self, client):
                self.chat = type("Chat", (), {"completions": Completions(client)})()

        monkeypatch.setattr(groq, "Groq", Groq)
        monkeypatch.setattr(instructor, "from_groq", Instructor)
        monkeypatch.setattr(llm_config, "_now", self.clock)


def _synthesize():
    return synthesizer.synthesize_node({
        "query": "Why are returns spiking?", "query_type": "returns", "plan": [],
        "tools_called": [], "messages": [HumanMessage(content="Why are returns spiking?")],
    })


# ── which client gets which profile ───────────────────────────────────────────

def test_the_profiles():
    fast, long = request_timeout(), request_timeout(long_output=True)
    assert (fast.read, fast.connect) == (20.0, 5.0)
    assert (long.read, long.connect) == (45.0, 5.0)


def test_the_agent_timeout_is_env_configurable(monkeypatch):
    monkeypatch.setenv("LLM_AGENT_REQUEST_TIMEOUT_S", "60")
    assert request_timeout(long_output=True).read == 60.0
    assert request_timeout().read == 20.0


def test_the_real_long_output_client():
    inner = groq_client(long_output=True).client
    assert (inner.timeout.read, inner.timeout.connect) == (45.0, 5.0)
    assert inner.max_retries == 1


def test_the_synthesizer_is_built_with_45s_and_one_retry(monkeypatch):
    sdk = SimulatedSDK(monkeypatch)
    _synthesize()
    assert sdk.built == [{"read": 45.0, "connect": 5.0, "max_retries": 1}]


def test_the_brief_is_built_with_45s_and_one_retry(monkeypatch):
    from backend.brief import generate

    sdk = SimulatedSDK(monkeypatch)
    generate._client.cache_clear()
    try:
        generate._client()
    finally:
        generate._client.cache_clear()   # never leave the simulated client cached
    assert sdk.built == [{"read": 45.0, "connect": 5.0, "max_retries": 1}]


def test_the_planner_stays_on_20s_and_the_sdk_retries(monkeypatch):
    sdk = SimulatedSDK(monkeypatch)
    planner.plan_node({"asin": "B08XPWDSWW", "product_name": "TOZO",
                       "query": "Why are returns spiking?"})
    assert sdk.built == [{"read": 20.0, "connect": 5.0, "max_retries": _SDK_DEFAULT_RETRIES}]


# ── a slow but healthy synthesis succeeds; a hang is still bounded ────────────

def test_a_35s_synthesis_succeeds_on_the_first_model(monkeypatch):
    sdk = SimulatedSDK(monkeypatch, generation_s=35.0)
    out = _synthesize()

    assert out["synthesis_degraded"] is False
    assert out["recommendation"].summary == "A real, model-written answer."
    assert sdk.tried == model_chain("agent")[:1]
    assert sdk.clock.t == 35.0


def test_the_same_synthesis_degraded_under_the_shared_20s(monkeypatch):
    """What fce3757b did: 3 x 20 s + 1.5 s = 61.5 s of abandoned tries, past
    the deadline, so the model never gets to answer."""
    monkeypatch.setenv("LLM_AGENT_REQUEST_TIMEOUT_S", "20")
    monkeypatch.setattr(llm_config, "LONG_OUTPUT_SDK_RETRIES", _SDK_DEFAULT_RETRIES)
    sdk = SimulatedSDK(monkeypatch, generation_s=35.0)
    out = _synthesize()

    assert out["synthesis_degraded"] is True
    assert sdk.tried == model_chain("agent")[:1]
    assert sdk.clock.t == 61.5


def test_a_hung_synthesizer_is_bounded_at_one_model(monkeypatch):
    """2 x 45 s + 0.5 s = 90.5 s, past the 45 s deadline, so no failover."""
    sdk = SimulatedSDK(monkeypatch, generation_s=None)
    out = _synthesize()

    assert out["synthesis_degraded"] is True
    assert sdk.tried == model_chain("agent")[:1]
    assert sdk.clock.t == 90.5


def test_a_synthesis_past_45s_is_regenerated_once_not_twice(monkeypatch):
    sdk = SimulatedSDK(monkeypatch, generation_s=50.0)
    out = _synthesize()

    assert out["synthesis_degraded"] is True
    assert sdk.clock.t == 90.5      # 2 abandoned generations, not 3 (136.5 s)
