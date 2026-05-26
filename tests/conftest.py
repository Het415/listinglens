"""Pytest configuration for ListingLens backend tests.

We use TestClient as a context manager so FastAPI's lifespan runs and
`app_state["supported_asins"]` is populated from disk. Without `with`,
the lifespan never fires and every ASIN-bearing test would see an empty
catalog.

ENV_MODE is pinned to "production" so the supported-asins set is
filtered to those with on-disk caches in data/processed/ — exactly the
state CI sees after a fresh checkout (the repo ships the precomputed
CSVs/JSONs). Pinning here keeps tests deterministic regardless of the
developer's local .env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is importable as `app` and `src.*` / `backend.*`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Pin deterministic config BEFORE importing app.py so module-level
# os.getenv() calls see these values.
os.environ.setdefault("ENV_MODE", "production")
# Tests must not hit real Redis; the cache module degrades to passthrough
# when REDIS_URL is unset.
os.environ.pop("REDIS_URL", None)


@pytest.fixture
def client():
    """FastAPI TestClient with lifespan executed.

    Using `with` is what triggers startup — that's where supported_asins
    gets populated. Otherwise /supported-asins returns an empty list and
    half the suite becomes meaningless.
    """
    from fastapi.testclient import TestClient
    from app import app

    # raise_server_exceptions=False makes TestClient surface unhandled
    # server-side exceptions as 500 responses (the same behavior real
    # clients see) instead of re-raising them in the test process. This
    # lets us assert on error status codes for endpoints with known
    # rough edges, without paving over the bug.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def any_supported_asin(client) -> str:
    """First ASIN advertised by the running app — skip if none available."""
    resp = client.get("/supported-asins")
    assert resp.status_code == 200
    asins = resp.json().get("asins", [])
    if not asins:
        pytest.skip("No precomputed ASINs available in data/processed/")
    return asins[0]["asin"]
