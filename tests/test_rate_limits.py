"""Per-IP rate limits, per-IP LLM allowance and the global daily LLM budget.

Context (audit E-05): every Groq-spending route was anonymous and unthrottled,
so one curl loop could drain every model's daily quota and take the Copilot
down until the UTC reset. See backend/http_limits.py for the three layers.

No test here reaches an LLM: the paths that would are either pre-exhausted so
the request is refused, or have the LLM function patched out.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app as app_module
from backend.http_limits import (
    DailyBudget,
    RequestLimits,
    TokenBucket,
    client_ip,
)

ORIGIN = "http://localhost:3000"
IP = "testclient"  # what Starlette's TestClient reports as the peer
ASIN = "B08XPWDSWW"


class FakeClock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeUtc:
    def __init__(self, dt: datetime) -> None:
        self.dt = dt

    def __call__(self) -> datetime:
        return self.dt


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def utc():
    return FakeUtc(datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc))


@pytest.fixture
def tight(monkeypatch, clock, utc):
    """Small limits on fake clocks, installed as the app's limiter."""
    limits = RequestLimits(per_minute=3, ip_allowance=16, daily_budget=24,
                           clock=clock, utcnow=utc)
    monkeypatch.setattr(app_module, "limits", limits)
    return limits


# ── Units ──────────────────────────────────────────────────────────────────────

def test_token_bucket_bursts_then_refills(clock):
    bucket = TokenBucket(3, 1 / 20, clock=clock)  # 3 per minute
    for _ in range(3):
        assert bucket.wait_for("a", 1) == 0
        bucket.take("a", 1)
    assert bucket.wait_for("a", 1) == pytest.approx(20)
    clock.advance(20)
    assert bucket.wait_for("a", 1) == 0


def test_token_bucket_keys_are_independent(clock):
    bucket = TokenBucket(1, 0.01, clock=clock)
    bucket.take("a", 1)
    assert bucket.wait_for("a", 1) > 0
    assert bucket.wait_for("b", 1) == 0


def test_token_bucket_memory_is_bounded(clock):
    bucket = TokenBucket(1, 1.0, clock=clock, max_keys=100)
    for i in range(1_000):
        bucket.take(f"ip{i}", 1)
    assert len(bucket._state) <= 100


def test_daily_budget_resets_at_utc_midnight():
    utc = FakeUtc(datetime(2026, 9, 23, 23, 59, 30, tzinfo=timezone.utc))
    budget = DailyBudget(10, now=utc)
    budget.spend(10)
    assert not budget.has_room(1)
    assert budget.seconds_until_reset() == 30
    utc.dt = datetime(2026, 9, 24, 0, 0, 1, tzinfo=timezone.utc)
    assert budget.has_room(10)
    assert budget.used == 0


def test_reservation_is_all_or_nothing(tight):
    """A budget refusal must not also eat the visitor's allowance."""
    tight.budget.spend(tight.budget.limit)
    before = tight.allowance.wait_for(IP, 16)
    assert tight.reserve_llm(IP, 8).layer == "budget"
    assert tight.allowance.wait_for(IP, 16) == before == 0


def test_one_address_cannot_spend_the_whole_budget(tight):
    """The done-when for T-02: an anonymous loop can't exhaust the day."""
    admitted = sum(tight.reserve_llm("loop", 8) is None for _ in range(100))
    assert admitted * 8 == 16  # the allowance, not the 24-call budget
    assert tight.budget.used < tight.budget.limit
    assert tight.reserve_llm("someone-else", 8) is None


@pytest.mark.parametrize("peer, xff, hops, expected", [
    ("10.0.0.5", None, 0, "10.0.0.5"),
    ("10.0.0.5", "203.0.113.9", 0, "10.0.0.5"),          # not trusted: ignore XFF
    ("10.0.0.5", "203.0.113.9", 1, "203.0.113.9"),
    ("10.0.0.5", "6.6.6.6, 203.0.113.9", 1, "203.0.113.9"),  # spoofed left entry
    ("10.0.0.5", "203.0.113.9, 172.16.0.1", 2, "203.0.113.9"),
    ("10.0.0.5", "203.0.113.9", 2, "10.0.0.5"),          # fewer entries than hops
    (None, None, 0, "unknown"),
])
def test_client_ip_counts_trusted_hops_from_the_right(peer, xff, hops, expected):
    assert client_ip(peer, xff, hops=hops) == expected


# ── JSON routes: 429 with CORS ─────────────────────────────────────────────────

def test_n_plus_first_request_in_the_window_is_429_with_cors(client, tight):
    app_module.app_state.setdefault("brief_cache", {})[ASIN] = {"asin": ASIN}
    codes = [client.get(f"/brief/{ASIN}", headers={"origin": ORIGIN}).status_code
             for _ in range(3)]
    assert codes == [200, 200, 200]

    res = client.get(f"/brief/{ASIN}", headers={"origin": ORIGIN})
    assert res.status_code == 429
    assert res.headers["access-control-allow-origin"] == ORIGIN
    assert int(res.headers["retry-after"]) == 20
    body = res.json()
    assert body["kind"] == "rate_limited"
    assert "20 seconds" in body["message"]
    app_module.app_state["brief_cache"].pop(ASIN)


def test_cached_brief_costs_no_llm_budget(client, tight):
    app_module.app_state.setdefault("brief_cache", {})[ASIN] = {"asin": ASIN}
    client.get(f"/brief/{ASIN}")
    assert tight.budget.used == 0
    app_module.app_state["brief_cache"].pop(ASIN)


def test_brief_on_an_exhausted_budget_is_429_quota_exhausted(client, tight):
    app_module.app_state.get("brief_cache", {}).pop(ASIN, None)
    tight.budget.spend(tight.budget.limit)
    res = client.get(f"/brief/{ASIN}", headers={"origin": ORIGIN})
    assert res.status_code == 429
    assert res.headers["access-control-allow-origin"] == ORIGIN
    assert res.json()["kind"] == "quota_exhausted"
    assert "00:00 UTC" in res.json()["message"]


def test_unknown_brief_asin_is_404_and_free(client, tight):
    assert client.get("/brief/B000000000").status_code == 404
    assert tight.budget.used == 0


def test_chat_is_rate_limited_before_any_work(client, tight, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a throttled /chat must not build a chain")

    monkeypatch.setattr(app_module, "run_full_pipeline", boom)
    for _ in range(3):
        tight.check_request(IP)
    res = client.post("/chat", json={"asin": ASIN, "question": "hi"},
                      headers={"origin": ORIGIN})
    assert res.status_code == 429
    assert res.headers["access-control-allow-origin"] == ORIGIN


# ── /intent/classify: the server decides on the LLM fallback ──────────────────

@pytest.fixture
def fake_intent(monkeypatch):
    calls: list[bool] = []

    def predict_intent(text, allow_llm=True):
        calls.append(allow_llm)
        if allow_llm:
            return {"category": "REFUND", "intent": "Refund", "confidence": 0.9, "source": "llm"}
        return {"category": "ACCOUNT", "intent": "Account", "confidence": 0.2, "source": "model"}

    import src.intent_classifier as ic
    monkeypatch.setattr(ic, "predict_intent", predict_intent)
    return calls


def test_intent_llm_fallback_runs_when_under_confident_and_budget_allows(client, tight, fake_intent):
    res = client.post("/intent/classify", json={"text": "where is my money"})
    assert res.json()["source"] == "llm"
    assert fake_intent == [False, True]
    assert tight.budget.used == 1


def test_intent_degrades_to_the_model_guess_when_the_budget_is_out(client, tight, fake_intent):
    tight.budget.spend(tight.budget.limit)
    res = client.post("/intent/classify", json={"text": "where is my money"})
    assert res.status_code == 200
    assert res.json()["source"] == "model"
    assert fake_intent == [False]


def test_client_can_no_longer_ask_for_the_llm(client, tight, fake_intent):
    """`allow_llm` from the body is ignored; the budget decides."""
    tight.budget.spend(tight.budget.limit)
    client.post("/intent/classify", json={"text": "where is my money", "allow_llm": True})
    assert fake_intent == [False]


def test_confident_intent_costs_no_budget(client, tight, monkeypatch):
    import src.intent_classifier as ic
    monkeypatch.setattr(ic, "predict_intent", lambda text, allow_llm=True: {
        "category": "ORDER", "intent": "Order", "confidence": 0.95, "source": "model"})
    client.post("/intent/classify", json={"text": "cancel my order"})
    assert tight.budget.used == 0


# ── SSE routes: an `error` frame the ErrorBubble can render ───────────────────

def _frames(res) -> list[tuple[str, str]]:
    out = []
    for block in res.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], lines["data"]))
    return out


@pytest.mark.parametrize("route, body", [
    ("/assistant/query", {"asin": ASIN, "query": "Why returns?", "mode": "copilot"}),
    ("/assistant/query", {"asin": ASIN, "query": "Why returns?", "mode": "quick"}),
    ("/agent/query", {"asin": ASIN, "query": "Why returns?"}),
])
def test_throttled_sse_route_sends_a_rate_limited_error_frame(client, tight, route, body):
    assert tight.reserve_llm(IP, 16) is None  # this visitor's allowance is spent
    res = client.post(route, json=body, headers={"origin": ORIGIN})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["access-control-allow-origin"] == ORIGIN
    frames = _frames(res)
    assert [event for event, _ in frames] == ["error"]
    import json
    payload = json.loads(frames[0][1])
    assert payload["kind"] == "rate_limited"
    assert payload["retry_after"] > 0


def test_exhausted_budget_sends_quota_exhausted_frame(client, tight):
    tight.budget.spend(tight.budget.limit)
    res = client.post("/assistant/query",
                      json={"asin": ASIN, "query": "Why returns?", "mode": "quick"})
    import json
    assert json.loads(_frames(res)[0][1])["kind"] == "quota_exhausted"


# ── Unlimited routes, docs, health ────────────────────────────────────────────

def test_health_and_warmup_are_never_throttled(client, tight, monkeypatch):
    monkeypatch.setattr(app_module, "_warm_asin_sync", lambda asin: None)
    for _ in range(3):
        tight.check_request(IP)
    assert tight.check_request(IP) is not None  # this IP is throttled...
    for _ in range(30):  # ...but the pingers' routes still answer
        assert client.get("/health").status_code == 200
        assert client.post("/warmup", json={"asin": ASIN}).status_code == 200


def test_health_reports_budget_and_denials(client, tight):
    tight.reserve_llm(IP, 8)
    for _ in range(4):
        tight.check_request(IP)
    limits = client.get("/health").json()["limits"]
    assert limits["llm_budget_used"] == 8
    assert limits["llm_budget_limit"] == 24
    assert limits["denied_since_start"] == {"rate": 1}


_DOCS_PROBE = """
from fastapi.testclient import TestClient
import app
c = TestClient(app.app)
print(*(c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")))
"""


@pytest.mark.parametrize("env_mode, expected", [
    ("production", "404 404 404"),
    ("development", "200 200 200"),
])
def test_api_docs_are_served_only_off_production(env_mode, expected):
    """A subprocess, because the docs routes are fixed when `app` is imported.

    In this process `app` may already have been imported under whatever
    ENV_MODE was set then: eval/run_eval.py calls load_dotenv(override=True),
    which copies a local .env's ENV_MODE=development into os.environ during
    collection. The conftest re-pins app.ENV_MODE, but not the routes.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "ENV_MODE": env_mode, "PYTHON_DOTENV_DISABLED": "1",
           "PYTHONPATH": str(root)}
    out = subprocess.run([sys.executable, "-c", _DOCS_PROBE], cwd=root, env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == expected
