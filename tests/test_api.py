"""Smoke tests for the ListingLens HTTP surface.

Scope: pure endpoints only — no LLM calls, no network egress, no Redis.
The /analyze tests use precomputed ASINs from data/processed/ so they
run offline. /agent/query and /assistant/query are excluded here because
they require a live GROQ_API_KEY; cover those in a separate integration
suite if needed.
"""

from __future__ import annotations


def test_root(client):
    res = client.get("/")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "ListingLens API"


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert "cached_asins" in body
    assert "supported_asins" in body


def test_supported_asins_shape(client):
    res = client.get("/supported-asins")
    assert res.status_code == 200
    body = res.json()
    assert "asins" in body
    assert isinstance(body["asins"], list)
    for entry in body["asins"]:
        assert "asin" in entry and "name" in entry


def test_analyze_rejects_empty_body(client):
    """Empty body — neither asin nor url_or_asin provided."""
    res = client.post("/analyze", json={})
    assert res.status_code == 400


def test_analyze_unknown_asin_in_production(client):
    """Unknown ASIN should 404 in production mode (no on-disk cache)."""
    res = client.post("/analyze", json={"asin": "B000000000"})
    assert res.status_code == 404


def test_analyze_known_asin_returns_cached_result(client, any_supported_asin):
    """Hits the disk-cache branch — no NLP pipeline, no LLM."""
    res = client.post("/analyze", json={"asin": any_supported_asin})
    assert res.status_code == 200
    body = res.json()
    assert body["asin"] == any_supported_asin
    assert "features" in body
    assert "risk" in body
    assert "summary" in body


def test_get_cached_analysis_404_when_uncached(client):
    """GET /analyze/{asin} only returns results already in app_state cache.

    A fresh client hasn't run POST /analyze for this ASIN yet, so even a
    supported ASIN should 404 until populated.
    """
    res = client.get("/analyze/B000000000")
    assert res.status_code == 404
