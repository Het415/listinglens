"""Pytest configuration for ListingLens backend tests.

We use TestClient as a context manager so FastAPI's lifespan runs and
`app_state["supported_asins"]` is populated from disk. Without `with`,
the lifespan never fires and every ASIN-bearing test would see an empty
catalog.

ENV_MODE is pinned to "production" so the supported-asins set is
filtered to those with on-disk caches in data/processed/ — exactly the
state CI sees after a fresh checkout (the repo ships the precomputed
CSVs/JSONs). Pinning here keeps tests deterministic regardless of the
developer's local .env *or* their exported shell environment.

That last part is load-bearing. This used to read:

    os.environ.setdefault("ENV_MODE", "production")

which is a no-op whenever ENV_MODE is *already* in the environment --
and something does put it there before this file is ever imported.

`deepeval` (installed via requirements-agent.txt) registers a `pytest11`
entry point, so pytest imports it during plugin loading, which happens
*before* conftest.py. That import calls `load_dotenv()`, which reads the
local .env -- where ENV_MODE=development -- and sets it. By the time
setdefault ran, the value was already present, so it did nothing.

The suite therefore ran in development mode: `run_full_pipeline` skipped
its production 404 guardrail, fell through to the heavy NLP branch, tried
to download a HuggingFace dataset for the deliberately-bogus ASIN
B000000000, and turned two 404 assertions into 500s while stretching the
suite from ~2 seconds to ~356 seconds.

It is tempting to conclude .env cannot be the culprit, because
`load_dotenv()` defaults to override=False and a value already in
os.environ always wins over the file. That reasoning holds only once
something has populated os.environ -- and at plugin-import time nothing
has, because conftest has not run yet. So the file wins. Verified by
A/B in one directory: `import deepeval` yields 'development' with .env
present and None with it removed, on a shell where ENV_MODE is unset.

CI was never affected: it exports ENV_MODE=production and has no .env.
This was local-only, and it predates the Groq model work -- it
reproduces on a pristine checkout of the commit before it.
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
# os.getenv() calls see these values. Assign unconditionally — an
# inherited ENV_MODE must lose to the test contract, not win.
os.environ["ENV_MODE"] = "production"
# Tests must not hit real Redis; the cache module degrades to passthrough
# when REDIS_URL is unset.
os.environ.pop("REDIS_URL", None)


@pytest.fixture(autouse=True)
def production_mode(monkeypatch):
    """Guarantee — and assert — that tests exercise production mode.

    The env var above covers app.py's import-time read. This fixture
    closes the remaining gaps:

    * `monkeypatch.setattr(app, "ENV_MODE", ...)` pins the module-level
      constant that `run_full_pipeline` and `lifespan` actually branch
      on, so we're correct even if `app` somehow got imported before
      this conftest ran (a plugin, a stray import, a future root
      conftest). raising=True is deliberate: if the constant is ever
      renamed or removed, these tests fail loudly instead of silently
      reverting to whatever the environment says.
    * `monkeypatch.chdir` pins the working directory, because
      `has_precomputed_cache` and `run_full_pipeline` resolve
      "data/processed/..." relative to cwd. Run pytest from anywhere
      else and the fixtures quietly see an empty catalog.

    monkeypatch undoes all of it at teardown, so we don't leak state
    into other suites.

    We use monkeypatch rather than pytest-env / an `env =` ini block
    because that would add a plugin dependency that isn't in
    requirements-dev.txt — and it still wouldn't cover app.ENV_MODE
    once the module is imported.
    """
    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setenv("ENV_MODE", "production")
    monkeypatch.delenv("REDIS_URL", raising=False)

    import app

    monkeypatch.setattr(app, "ENV_MODE", "production")

    # Regression tripwire. If this ever fails, the suite is about to
    # run the heavy NLP path: network egress, HuggingFace downloads,
    # and 500s where the production guardrail should return 404.
    assert app.ENV_MODE == "production", (
        f"tests must run in production mode, got {app.ENV_MODE!r}"
    )


@pytest.fixture
def client(production_mode):
    """FastAPI TestClient with lifespan executed.

    Using `with` is what triggers startup — that's where supported_asins
    gets populated. Otherwise /supported-asins returns an empty list and
    half the suite becomes meaningless.

    Depends on `production_mode` explicitly (not just via autouse) so the
    ENV_MODE pin is guaranteed to be in place before lifespan reads it to
    filter the supported-ASIN catalog.
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
