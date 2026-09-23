"""The public API refuses oversized bodies and out-of-bounds fields.

Context (audit E-06 / CMD-16): one anonymous 50 MB POST to /chat pushed the
server from 473 to 666 MiB against Render's 512 MiB cap, because FastAPI
buffers and parses the whole body before validation runs. These tests pin the
413 cap in backend/http_limits.py and the field bounds on the request models.

Everything here fails before any handler runs, so no LLM, network or Redis.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.http_limits import MAX_BODY_BYTES, BodySizeLimitMiddleware

ORIGIN = "http://localhost:3000"

POST_ROUTES = [
    "/analyze",
    "/chat",
    "/agent/query",
    "/agent/query/mock",
    "/assistant/query",
    "/warmup",
    "/intent/classify",
]

VALID = {"asin": "B08XPWDSWW", "query": "Why are returns spiking?"}


def _oversize_json() -> bytes:
    return b'{"asin":"B08XPWDSWW","query":"' + b"a" * (MAX_BODY_BYTES + 1) + b'"}'


# ── Body cap ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", POST_ROUTES)
def test_declared_oversize_body_is_413_on_every_post_route(client, route):
    res = client.post(
        route,
        content=_oversize_json(),
        headers={"content-type": "application/json", "origin": ORIGIN},
    )
    assert res.status_code == 413
    assert res.json()["max_bytes"] == MAX_BODY_BYTES


@pytest.mark.parametrize("route", POST_ROUTES)
def test_413_carries_cors_headers(client, route):
    """Without ACAO the browser hides the 413 and the UI reports a network error."""
    res = client.post(
        route,
        content=_oversize_json(),
        headers={"content-type": "application/json", "origin": ORIGIN},
    )
    assert res.headers.get("access-control-allow-origin") == ORIGIN


def test_chunked_body_without_content_length_is_413(client):
    """A generator body goes out chunked, with no Content-Length to check."""
    def chunks():
        yield _oversize_json()

    res = client.post(
        "/chat",
        content=chunks(),
        headers={"content-type": "application/json", "origin": ORIGIN},
    )
    assert "content-length" not in {k.lower() for k in res.request.headers}
    assert res.status_code == 413
    assert res.headers.get("access-control-allow-origin") == ORIGIN


def test_body_at_the_cap_is_not_refused(client):
    """Exactly MAX_BODY_BYTES is allowed; the handler's own validation answers."""
    prefix = b'{"text":"'
    suffix = b'"}'
    body = prefix + b"a" * (MAX_BODY_BYTES - len(prefix) - len(suffix)) + suffix
    assert len(body) == MAX_BODY_BYTES
    res = client.post("/intent/classify", content=body,
                      headers={"content-type": "application/json"})
    # Under the byte cap, over the field bound: a 422, not a 413.
    assert res.status_code == 422


def _run_asgi(app, messages: list[dict]) -> list[dict]:
    """Drive an ASGI app with a scripted receive(); return what it sent."""
    sent: list[dict] = []
    pending = list(messages)

    async def receive():
        if pending:
            return pending.pop(0)
        await asyncio.sleep(3600)  # a real server would wait for the client

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/chat", "raw_path": b"/chat",
        "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80),
    }
    asyncio.run(asyncio.wait_for(app(scope, receive, send), timeout=10))
    return sent


def test_streamed_chunks_are_counted_across_messages():
    """Many small chunks that only add up to more than the cap."""
    from app import app

    chunk = b"a" * 8192
    n = MAX_BODY_BYTES // len(chunk) + 2
    messages = [{"type": "http.request", "body": chunk, "more_body": True}
                for _ in range(n)]
    sent = _run_asgi(app, messages)

    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert [m["status"] for m in starts] == [413], "exactly one response, and it is the 413"


def test_middleware_stops_reading_at_the_cap():
    """The app never sees the bytes past the cap, so memory stays bounded."""
    reads = 0

    async def greedy_app(scope, receive, send):
        nonlocal reads
        while True:
            message = await receive()
            reads += 1
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunk = b"a" * 8192
    total_chunks = 1000  # 8 MB offered
    messages = [{"type": "http.request", "body": chunk, "more_body": True}
                for _ in range(total_chunks)]
    sent = _run_asgi(BodySizeLimitMiddleware(greedy_app), messages)

    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [413]
    # The cap is 8 chunks; the 9th read raises. The app never gets the rest.
    assert reads == MAX_BODY_BYTES // len(chunk)
    assert reads < total_chunks


# ── Field bounds ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", ["/agent/query", "/assistant/query"])
@pytest.mark.parametrize("override", [
    {"query": "a" * 2001},
    {"query": ""},
    {"asin": "b08xpwdsww"},
    {"asin": "B08XPWDSWW/../x"},
    {"image_urls": ["https://example.com/a.jpg"] * 13},
    {"image_urls": ["https://example.com/" + "a" * 2048]},
    {"main_index": -1},
    {"main_index": 12},
    {"audit_id": "../../healthz"},
    {"audit_id": "a" * 65},
])
def test_out_of_bounds_agent_fields_are_422(client, route, override):
    res = client.post(route, json={**VALID, **override})
    assert res.status_code == 422, res.text


def test_unknown_mode_is_rejected_not_upgraded_to_copilot(client):
    res = client.post("/assistant/query", json={**VALID, "mode": "Copilot"})
    assert res.status_code == 422


@pytest.mark.parametrize("body", [
    {"asin": "B08XPWDSWW", "question": "a" * 2001},
    {"asin": "not-an-asin", "question": "What do people like?"},
])
def test_out_of_bounds_chat_fields_are_422(client, body):
    assert client.post("/chat", json=body).status_code == 422


def test_oversize_intent_text_is_422(client):
    assert client.post("/intent/classify", json={"text": "a" * 2001}).status_code == 422


@pytest.mark.parametrize("body", [
    {"asin": "B08XPWDSWW!"},
    {"url_or_asin": "https://amazon.com/dp/" + "a" * 2048},
    {"asin": "B08XPWDSWW", "max_reviews": 0},
    {"asin": "B08XPWDSWW", "max_reviews": 100_000},
])
def test_out_of_bounds_analyze_fields_are_422(client, body):
    assert client.post("/analyze", json=body).status_code == 422


def test_warmup_rejects_a_malformed_asin(client):
    assert client.post("/warmup", json={"asin": "x" * 50}).status_code == 422


def test_url_or_asin_still_accepts_a_full_amazon_url(client):
    """The ASIN pattern is on `asin` only; URLs are parsed by extract_asin."""
    res = client.post(
        "/analyze",
        json={"url_or_asin": "https://www.amazon.com/dp/B000000000?ref=x"},
    )
    assert res.status_code == 404  # parsed fine; not a precomputed ASIN
