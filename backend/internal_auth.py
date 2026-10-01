"""Shared-secret check between the Next.js proxy and this API.

Why it exists
-------------
Every route here is anonymous, and the Groq-spending ones are reachable by
anyone who reads the API URL out of the frontend bundle. The rate limits in
backend/http_limits.py bound the damage, but the only caller that should exist
is the frontend. So the frontend calls a Next.js server-side proxy, and the
proxy adds `X-Internal-Secret`, a value the browser never sees. Anything that
arrives without it is not the site.

Dormant until configured
------------------------
With `BACKEND_SHARED_SECRET` unset (or empty) the check is off and every
request passes, exactly as before. Setting it is the rollout switch; unsetting
it is the rollback. Both env vars are read per request, so neither needs a
code change, and tests can flip them with monkeypatch.

`BACKEND_SHARED_SECRET_PREVIOUS` is also accepted, so the secret can rotate
without a window where Render and Vercel disagree. See docs/INTERNAL_AUTH.md.

Exempt
------
`/`, `/health` and `/warmup` stay open: the Docker HEALTHCHECK, the uptime and
warmup pingers (launchd, cron-job.org, the GitHub Actions cron) call them with
no secret, and none of them spends LLM tokens. So do OPTIONS requests, so a
CORS preflight can never be refused here.

Order
-----
Register this BEFORE `BodySizeLimitMiddleware` (so it is inside it): an
oversize body is refused with 413 before this check runs, and CORS, outermost,
still decorates the 401.
"""

from __future__ import annotations

import hmac
import json
import os

from backend.http_limits import ASGIApp, Receive, Scope, Send

SECRET_ENV = "BACKEND_SHARED_SECRET"
PREVIOUS_SECRET_ENV = "BACKEND_SHARED_SECRET_PREVIOUS"
HEADER = b"x-internal-secret"

# Exact matches. A new route is protected by default; opening one is a
# deliberate edit here.
EXEMPT_PATHS = frozenset({"/", "/health", "/warmup"})


def _secret(name: str) -> str:
    # Stripped: a dashboard paste with a trailing newline would otherwise
    # refuse every request, since HTTP clients strip header whitespace.
    return os.getenv(name, "").strip()


def _as_bytes(value: str) -> bytes:
    # Starlette decodes header values as latin-1, so encoding back recovers the
    # wire bytes. Anything outside latin-1 cannot have come off the wire.
    try:
        return value.encode("latin-1")
    except UnicodeEncodeError:
        return value.encode("utf-8")


def enforced() -> bool:
    """True once BACKEND_SHARED_SECRET is set on this process."""
    return bool(_secret(SECRET_ENV))


def secret_matches(header_value: str | None) -> bool:
    """Whether a header value is the current or previous secret.

    False whenever the check is off: nothing is "authenticated" then, so
    callers must not grant a secret-holder's trust (see app._ip).
    """
    current = _secret(SECRET_ENV)
    if not current or header_value is None:
        return False
    given = _as_bytes(header_value)
    accepted = [s for s in (current, _secret(PREVIOUS_SECRET_ENV)) if s]
    # Every candidate is compared, so the timing doesn't say which one matched.
    results = [hmac.compare_digest(given, _as_bytes(s)) for s in accepted]
    return any(results)


def startup_notice() -> str:
    if not enforced():
        return f"[internal_auth] {SECRET_ENV} unset — every route is publicly callable"
    also = " (previous secret also accepted)" if _secret(PREVIOUS_SECRET_ENV) else ""
    return f"[internal_auth] enforced{also}; open: {', '.join(sorted(EXEMPT_PATHS))}"


# Log the first refusal of each kind per process. "mismatch" is the one that
# means a misconfigured proxy; "missing" is usually a scanner.
_logged_reasons: set[str] = set()


async def _unauthorized(send: Send) -> None:
    # Deliberately says nothing about why: missing and wrong look the same.
    payload = json.dumps({"detail": "unauthorized"}).encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            # Any request body is left unread on the socket.
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class InternalSecretMiddleware:
    """Pure ASGI middleware: 401 unless `X-Internal-Secret` matches, once enforced."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] != "http"
                or scope.get("method") == "OPTIONS"
                or scope.get("path") in EXEMPT_PATHS
                or not enforced()):
            await self.app(scope, receive, send)
            return

        raw = next((v for k, v in scope.get("headers", []) if k == HEADER), None)
        if raw is not None and secret_matches(raw.decode("latin-1")):
            await self.app(scope, receive, send)
            return

        reason = "missing" if raw is None else "mismatch"
        if reason not in _logged_reasons:
            _logged_reasons.add(reason)
            print(f"[internal_auth] refused {scope.get('method')} {scope.get('path')}: "
                  f"secret header {reason} (logged once per process)", flush=True)
        await _unauthorized(send)
