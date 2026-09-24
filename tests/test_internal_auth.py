"""The shared-secret check between the Next.js proxy and this API.

See backend/internal_auth.py and docs/INTERNAL_AUTH.md. The check is off until
BACKEND_SHARED_SECRET is set, and both secrets are read per request, so every
test flips them with monkeypatch (conftest clears them first).

Nothing here reaches an LLM: the protected route used is /supported-asins, and
the rate-limit test serves /brief from its cache.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

import app as app_module
from backend import internal_auth
from backend.http_limits import MAX_BODY_BYTES, RequestLimits
from backend.internal_auth import InternalSecretMiddleware

ORIGIN = "http://localhost:3000"
CURRENT = "current-secret-0123456789abcdef"
PREVIOUS = "previous-secret-fedcba9876543210"
PROTECTED = "/supported-asins"
ASIN = "B08XPWDSWW"


@pytest.fixture
def enforced(monkeypatch):
    monkeypatch.setenv("BACKEND_SHARED_SECRET", CURRENT)
    monkeypatch.setenv("BACKEND_SHARED_SECRET_PREVIOUS", PREVIOUS)


def _secret(value: str) -> dict:
    return {"x-internal-secret": value}


# ── Off until configured ──────────────────────────────────────────────────────

def test_unset_secret_leaves_every_route_open(client):
    assert not internal_auth.enforced()
    assert client.get(PROTECTED).status_code == 200


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_empty_secret_counts_as_unset(client, monkeypatch, value):
    monkeypatch.setenv("BACKEND_SHARED_SECRET", value)
    assert not internal_auth.enforced()
    assert client.get(PROTECTED).status_code == 200


def test_nothing_matches_while_the_check_is_off(monkeypatch):
    """Even the previous secret: with the check off, nobody holds the secret."""
    monkeypatch.setenv("BACKEND_SHARED_SECRET_PREVIOUS", PREVIOUS)
    assert not internal_auth.secret_matches(PREVIOUS)
    assert not internal_auth.secret_matches("")
    assert not internal_auth.secret_matches(None)


# ── Enforced ──────────────────────────────────────────────────────────────────

def test_missing_header_is_401(client, enforced):
    res = client.get(PROTECTED)
    assert res.status_code == 401
    assert res.json() == {"detail": "unauthorized"}


@pytest.mark.parametrize("value", ["wrong", "", CURRENT + "x", CURRENT[:-1], "third-value"])
def test_wrong_header_is_401(client, enforced, value):
    res = client.get(PROTECTED, headers=_secret(value))
    assert res.status_code == 401
    assert res.json() == {"detail": "unauthorized"}


@pytest.mark.parametrize("value", [CURRENT, PREVIOUS])
def test_current_and_previous_secrets_pass(client, enforced, value):
    assert client.get(PROTECTED, headers=_secret(value)).status_code == 200


def test_previous_stops_working_once_cleared(client, enforced, monkeypatch):
    monkeypatch.delenv("BACKEND_SHARED_SECRET_PREVIOUS")
    assert client.get(PROTECTED, headers=_secret(PREVIOUS)).status_code == 401
    assert client.get(PROTECTED, headers=_secret(CURRENT)).status_code == 200


def test_secret_env_is_read_per_request(client, monkeypatch):
    """No restart between turning it on and off: that's the rollback path."""
    assert client.get(PROTECTED).status_code == 200
    monkeypatch.setenv("BACKEND_SHARED_SECRET", CURRENT)
    assert client.get(PROTECTED).status_code == 401
    monkeypatch.delenv("BACKEND_SHARED_SECRET")
    assert client.get(PROTECTED).status_code == 200


def test_non_latin1_header_value_does_not_crash(enforced):
    """secret_matches is public; a str Starlette could never produce is just False."""
    assert not internal_auth.secret_matches("€" + CURRENT)


def test_401_carries_cors_headers(client, enforced):
    """CORS is outermost, so a refused browser call can read its status."""
    res = client.get(PROTECTED, headers={"origin": ORIGIN})
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == ORIGIN


def test_a_new_route_is_protected_by_default(client, enforced):
    """Unknown paths are refused before routing, not 404'd."""
    assert client.get("/no-such-route").status_code == 401
    assert client.get("/health/").status_code == 401  # exact match only


# ── Exempt paths and methods ──────────────────────────────────────────────────

def test_root_and_health_stay_open(client, enforced):
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200


def test_warmup_stays_open(client, enforced, monkeypatch):
    monkeypatch.setattr(app_module, "_warm_asin_sync", lambda asin: None)
    assert client.post("/warmup", json={"asin": ASIN}).status_code == 200


def test_health_reports_whether_the_check_is_on(client, monkeypatch):
    assert client.get("/health").json()["internal_auth"] == "off"
    monkeypatch.setenv("BACKEND_SHARED_SECRET", CURRENT)
    assert client.get("/health").json()["internal_auth"] == "enforced"


def test_cors_preflight_is_not_refused(client, enforced):
    res = client.options(PROTECTED, headers={
        "origin": ORIGIN,
        "access-control-request-method": "GET",
        "access-control-request-headers": "content-type",
    })
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ORIGIN


def test_bare_options_reaches_the_app(client, enforced):
    """Not a preflight, so CORS passes it on; the router's 405, not our 401."""
    assert client.options(PROTECTED).status_code != 401


# ── Ordering: the body cap runs first ─────────────────────────────────────────

def _oversize_json() -> bytes:
    return b'{"asin":"B08XPWDSWW","query":"' + b"a" * (MAX_BODY_BYTES + 1) + b'"}'


@pytest.mark.parametrize("route", ["/chat", "/assistant/query", "/warmup"])
def test_oversize_body_is_413_not_401(client, enforced, route):
    res = client.post(route, content=_oversize_json(),
                      headers={"content-type": "application/json", "origin": ORIGIN})
    assert res.status_code == 413
    assert res.headers.get("access-control-allow-origin") == ORIGIN


# ── Non-HTTP scopes ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_non_http_scopes_pass_through(monkeypatch, scope_type):
    monkeypatch.setenv("BACKEND_SHARED_SECRET", CURRENT)
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    async def noop(*_):
        return {}

    scope = {"type": scope_type, "path": PROTECTED, "headers": []}
    asyncio.run(InternalSecretMiddleware(inner)(scope, noop, noop))
    assert seen == [scope_type]


def test_app_boots_with_the_secret_set(monkeypatch, capsys):
    """Lifespan runs through the middleware too, and logs the mode once."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BACKEND_SHARED_SECRET", CURRENT)
    with TestClient(app_module.app) as c:
        assert c.get(PROTECTED, headers=_secret(CURRENT)).status_code == 200
    assert "[internal_auth] enforced" in capsys.readouterr().out


def test_startup_warns_when_unset(capsys):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app):
        pass
    out = capsys.readouterr().out
    assert "[internal_auth] BACKEND_SHARED_SECRET unset — every route is publicly callable" in out


# ── The visitor's address: X-Client-IP only with a valid secret ───────────────

def _request(headers: dict, peer: str = "10.0.0.5") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    })


def test_client_ip_header_is_used_with_a_valid_secret(enforced):
    assert app_module._ip(_request({**_secret(CURRENT), "x-client-ip": "8.8.8.8"})) == "8.8.8.8"
    assert app_module._ip(_request({**_secret(PREVIOUS), "x-client-ip": "8.8.8.8"})) == "8.8.8.8"


def test_client_ip_header_is_normalized(enforced):
    req = _request({**_secret(CURRENT), "x-client-ip": " 2001:DB8:0:0::1 "})
    assert app_module._ip(req) == "2001:db8::1"


@pytest.mark.parametrize("headers", [
    {"x-client-ip": "8.8.8.8"},                                   # no secret
    {**_secret("wrong"), "x-client-ip": "8.8.8.8"},               # wrong secret
    {**_secret(CURRENT), "x-client-ip": "not-an-ip"},             # unparseable
    {**_secret(CURRENT), "x-client-ip": "8.8.8.8, 9.9.9.9"},      # a list, not one address
    {**_secret(CURRENT), "x-client-ip": ""},
    {**_secret(CURRENT)},                                         # header absent
])
def test_client_ip_header_is_ignored_otherwise(enforced, headers):
    assert app_module._ip(_request(headers)) == "10.0.0.5"


def test_client_ip_header_is_ignored_while_the_check_is_off():
    """With no secret configured, anyone could send it."""
    req = _request({**_secret(CURRENT), "x-client-ip": "8.8.8.8"})
    assert app_module._ip(req) == "10.0.0.5"


def test_proxied_visitors_get_separate_rate_limit_buckets(client, enforced, monkeypatch):
    """End to end: the limiter keys on X-Client-IP behind the proxy, and a
    direct caller can't escape its bucket by rotating the header."""
    monkeypatch.setattr(app_module, "limits", RequestLimits(per_minute=1))
    app_module.app_state.setdefault("brief_cache", {})[ASIN] = {"asin": ASIN}
    try:
        def get(ip: str, secret: str = CURRENT) -> int:
            return client.get(f"/brief/{ASIN}",
                              headers={**_secret(secret), "x-client-ip": ip}).status_code

        assert [get("8.8.8.8"), get("8.8.8.8"), get("9.9.9.9")] == [200, 429, 200]

        monkeypatch.delenv("BACKEND_SHARED_SECRET")
        monkeypatch.setattr(app_module, "limits", RequestLimits(per_minute=1))
        assert [get("8.8.8.8", ""), get("9.9.9.9", "")] == [200, 429]
    finally:
        app_module.app_state["brief_cache"].pop(ASIN)


# ── CORS ──────────────────────────────────────────────────────────────────────

def test_cors_no_longer_allows_credentials(client):
    """Audit E-68: the frontend sends no credentials, so none are allowed."""
    simple = client.get("/health", headers={"origin": ORIGIN})
    preflight = client.options(PROTECTED, headers={
        "origin": ORIGIN, "access-control-request-method": "POST"})
    for res in (simple, preflight):
        assert res.headers.get("access-control-allow-origin") == ORIGIN
        assert "access-control-allow-credentials" not in res.headers
