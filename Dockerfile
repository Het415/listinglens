# ── ListingLens backend image ─────────────────────────────────────────────────
# Single-stage build on python:3.11-slim. We don't need a separate builder
# stage because the project is pure Python — no compile step, no static
# assets to bundle. `--prefer-binary` is critical: torch, faiss-cpu, and
# transformers all ship manylinux wheels; without `--prefer-binary` pip
# will sometimes choose a source distribution and the build takes 20+ min.
#
# Layer ordering follows the standard "deps file first, source last"
# pattern so editing app.py doesn't bust the heavy pip-install layer.

FROM python:3.11-slim

# PYTHONDONTWRITEBYTECODE — no .pyc files (smaller image, faster startup
#                          on read-only filesystems).
# PYTHONUNBUFFERED       — stream stdout/stderr live to `docker logs`
#                          instead of buffering until newline-batched.
# PIP_NO_CACHE_DIR       — don't keep wheel cache after install (~200MB).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl is only here for HEALTHCHECK. Strip apt lists in the same RUN so
# they don't bloat the layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Heavy layer. Stays cached until requirements.txt itself changes.
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefer-binary -r requirements.txt

# Source code — cheap layer, rebuilt on every code change.
COPY . .

# Run as a non-root UID. Even though containers aren't a security
# boundary you should rely on, running app code as root makes any
# escape exponentially worse. UID 1000 matches the typical host user
# so bind-mounted files stay readable/writable.
RUN useradd --create-home --uid 1000 app \
 && chown -R app:app /app
USER app

EXPOSE 8000

# Same endpoint the architecture spec mandates. 20s start-period gives
# the lifespan task (precomputed-ASIN scan) time to settle before Docker
# starts marking the container unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# Production CMD — overridden by docker-compose to add --reload for the
# dev hot-reload loop.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
