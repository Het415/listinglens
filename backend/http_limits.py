"""Request-size, rate and budget guards for the public API.

Two independent protections live here: the body cap (next section) and the
rate/budget limiter (see "Rate and budget limits" further down).

Body cap: why it exists
-----------------------
FastAPI reads a JSON body with `await request.body()`, which accumulates every
chunk and joins them (peak about 2x the body), then `json.loads` it, all before
pydantic gets to reject anything. uvicorn 0.32 has no body limit of its own. So
a single anonymous POST of a few tens of MB could OOM the 512 MiB Render
instance: on 2026-09-23 one 50 MB POST to /chat took RSS from 473 to 666 MiB
and still came back 404 (audit CMD-16).

`Field(max_length=...)` on the request models does not help here, because
validation runs only after the whole body is in memory. The cap has to sit
below FastAPI, at the ASGI layer, where the bytes arrive.

Two paths, because a client does not have to declare its size
-------------------------------------------------------------
1. `Content-Length` above the cap: answer 413 without calling the app or
   reading the body. uvicorn only sends `100 Continue` once the app first
   calls `receive()`, so a client that waits for it (curl does for large
   bodies) never uploads the payload at all.
2. Chunked or understated bodies: count the `http.request` bytes as the app
   reads them, and stop at the cap. FastAPI turns any exception raised while
   it reads the body into its own 400 ("There was an error parsing the
   body"), so the middleware drops that response and sends the 413 itself.

Order matters
-------------
Register this BEFORE `CORSMiddleware`. `add_middleware` makes the last-added
middleware the outermost, so CORS then wraps this one and the 413 carries the
`access-control-allow-origin` header. Without it the browser hides the status
and the frontend can only report a network failure.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# 64 KB. The largest body the request models accept is an /assistant/query
# with a 2,000-char question and 12 image URLs of 2,048 chars: about 50 KB even
# if every question character is an escaped emoji. The browser sends a few
# hundred bytes. Raise this constant if a real client ever needs more.
MAX_BODY_BYTES = 64 * 1024

TOO_LARGE_DETAIL = (
    "Request body is too large for this API. Questions are limited to a few "
    "thousand characters."
)


class _BodyTooLarge(Exception):
    """Raised into the app's `receive()` once the streamed body passes the cap."""


async def _send_json(send: Send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            # The unread body is still on the socket, so the connection cannot
            # be reused for another request.
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class BodySizeLimitMiddleware:
    """Pure ASGI middleware: 413 for any HTTP request body over `max_bytes`."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        too_large = {"detail": TOO_LARGE_DETAIL, "max_bytes": self.max_bytes}

        # Path 1: the client declared its size up front.
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    # uvicorn's parser rejects a malformed Content-Length before
                    # the app sees it; if one slips through, the byte count
                    # below still applies.
                    break
                if declared > self.max_bytes:
                    await _send_json(send, 413, too_large)
                    return
                break

        # Path 2: count what actually arrives.
        received = 0
        exceeded = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            # Once over the cap, whatever the app sends is its reaction to our
            # exception (FastAPI's 400). Drop it; the 413 below replaces it.
            if exceeded and not response_started:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            pass

        if exceeded and not response_started:
            await _send_json(send, 413, too_large)


# ── Rate and budget limits ─────────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


# Render sets RENDER=true in every service; one hop is its proxy. Anywhere else
# the TCP peer is the client, unless TRUSTED_PROXY_HOPS says otherwise.
TRUSTED_PROXY_HOPS = _env_int("TRUSTED_PROXY_HOPS", 1 if os.getenv("RENDER") else 0)

_ip_logged = False


def client_ip(peer: str | None, forwarded_for: str | None,
              hops: int | None = None) -> str:
    """The address to rate-limit by.

    Behind Render's proxy the TCP peer is the proxy, so every visitor would share
    one bucket. The client IP comes from `X-Forwarded-For`, counted from the right:
    each trusted proxy appends the address it received the connection from, so the
    entry `TRUSTED_PROXY_HOPS` from the right was written by our own proxy and
    cannot be forged. The leftmost entry can: a client can send any
    `X-Forwarded-For` it likes, and proxies append to it. That is why this does not
    rely on uvicorn's `--forwarded-allow-ips='*'`, which takes the leftmost entry.
    """
    global _ip_logged
    hops = TRUSTED_PROXY_HOPS if hops is None else hops
    ip = peer or "unknown"
    if hops > 0 and forwarded_for:
        chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        # Fewer entries than trusted hops means the header did not come through
        # our proxies as configured; fall back to the peer, as ProxyFix does.
        if len(chain) >= hops:
            ip = chain[-hops]
    if not _ip_logged:
        # Once per process, so the owner can check TRUSTED_PROXY_HOPS against
        # what the platform actually sends (see IMPLEMENTATION_LOG.md, T-02).
        _ip_logged = True
        print(f"[limits] client IP resolution: peer={peer} "
              f"x-forwarded-for={forwarded_for!r} hops={hops} -> {ip}", flush=True)
    return ip


class TokenBucket:
    """Per-key token bucket. Callers hold RequestLimits' lock."""

    def __init__(self, capacity: float, per_second: float, *,
                 clock: Callable[[], float] = time.monotonic,
                 max_keys: int = 10_000) -> None:
        self.capacity = capacity
        self.per_second = per_second
        self.clock = clock
        self.max_keys = max_keys
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tokens, at)

    def _level(self, key: str, now: float) -> float:
        tokens, at = self._state.get(key, (self.capacity, now))
        return min(self.capacity, tokens + (now - at) * self.per_second)

    def wait_for(self, key: str, cost: float) -> float:
        """Seconds until `cost` tokens are available; 0 means now."""
        level = self._level(key, self.clock())
        if level >= cost:
            return 0.0
        if cost > self.capacity or self.per_second <= 0:
            return math.inf
        return (cost - level) / self.per_second

    def take(self, key: str, cost: float) -> None:
        now = self.clock()
        self._state[key] = (self._level(key, now) - cost, now)
        if len(self._state) > self.max_keys:
            self._prune(now)

    def _prune(self, now: float) -> None:
        # A bucket that has refilled is indistinguishable from a new one.
        for key in [k for k in self._state if self._level(k, now) >= self.capacity]:
            del self._state[key]
        # Still too many live keys: drop the least recently used half.
        if len(self._state) > self.max_keys:
            by_age = sorted(self._state, key=lambda k: self._state[k][1])
            for key in by_age[: len(by_age) // 2]:
                del self._state[key]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DailyBudget:
    """A count that resets at 00:00 UTC, when Groq's daily limits reset."""

    def __init__(self, limit: int, *, now: Callable[[], datetime] = _utcnow) -> None:
        self.limit = limit
        self.now = now
        self.day = now().date()
        self.used = 0
        self._announced: set[int] = set()

    def _roll(self) -> datetime:
        now = self.now()
        if now.date() != self.day:
            self.day, self.used, self._announced = now.date(), 0, set()
        return now

    def seconds_until_reset(self) -> int:
        now = self._roll()
        midnight = datetime.combine(now.date() + timedelta(days=1),
                                    datetime.min.time(), tzinfo=timezone.utc)
        return max(1, math.ceil((midnight - now).total_seconds()))

    def has_room(self, cost: int) -> bool:
        self._roll()
        return self.used + cost <= self.limit

    def spend(self, cost: int) -> None:
        self._roll()
        self.used += cost
        # The daily usage line the audit's guardrails ask for, at 50/80/100%.
        for pct in (50, 80, 100):
            if self.used * 100 >= pct * self.limit and pct not in self._announced:
                self._announced.add(pct)
                print(f"[limits] daily LLM budget at {pct}%: {self.used}/{self.limit} "
                      f"estimated calls (resets 00:00 UTC)", flush=True)


def _humanize(seconds: float) -> str:
    seconds = max(1, math.ceil(seconds))
    if seconds < 90:
        return f"{seconds} seconds"
    minutes = math.ceil(seconds / 60)
    if minutes < 90:
        return f"{minutes} minutes"
    return f"{minutes // 60} h {minutes % 60} min"


@dataclass(frozen=True)
class Denial:
    """Why a request was refused. `as_payload()` is the SSE and 429 body."""

    layer: str        # "rate" | "allowance" | "budget"
    kind: str         # the frontend ErrorBubble's `kind`
    message: str
    retry_after: int  # seconds

    def as_payload(self) -> dict:
        return {"message": self.message, "kind": self.kind,
                "retry_after": self.retry_after}


class RequestLimits:
    """Three limits on the LLM routes, behind one lock.

    Every Groq-spending route used to be anonymous and unthrottled, and the model
    failover spreads a flood across every model's daily bucket. A short curl loop
    could take the Copilot down for everyone until the UTC reset (audit E-05). The
    free tier allows 200k tokens per model per day, roughly 30 Copilot runs per
    model (HANDOFF.md), and the eval spends from the same key.

    1. Request rate per client IP: flood control on the LLM routes, including
       their cheap paths (a cached brief, a confident intent guess).
    2. LLM allowance per client IP: a slow-refilling bucket of estimated LLM calls.
       This is what stops one address from exhausting the day: at the defaults a
       single address gets at most 48 + 48 calls a day, about a third of the budget.
    3. Global daily budget of estimated LLM calls, reset at 00:00 UTC. Whatever
       the traffic, the demo never spends more than this.

    Layers 2 and 3 are charged together, all-or-nothing, before the first LLM call.
    The costs are estimates, not meters: real per-call token metering is T-15.

    State is in-process, which is correct for the single uvicorn worker this runs
    as. It resets on restart, which errs toward serving: a restart is at most one
    extra allowance.

    Sync routes run in the threadpool and async ones on the event loop, so
    both can call in at once; every critical section is a few dict operations.
    """

    def __init__(self, *, per_minute: int = 20, ip_allowance: int = 48,
                 daily_budget: int = 300,
                 clock: Callable[[], float] = time.monotonic,
                 utcnow: Callable[[], datetime] = _utcnow) -> None:
        self.requests = TokenBucket(per_minute, per_minute / 60, clock=clock)
        self.allowance = TokenBucket(ip_allowance, ip_allowance / 86_400, clock=clock)
        self.budget = DailyBudget(daily_budget, now=utcnow)
        self.denied: Counter[str] = Counter()
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "RequestLimits":
        return cls(
            per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 20),
            ip_allowance=_env_int("LLM_CALLS_PER_IP_PER_DAY", 48),
            daily_budget=_env_int("LLM_DAILY_BUDGET", 300),
        )

    def _deny(self, layer: str, kind: str, message: str, wait: float) -> Denial:
        self.denied[layer] += 1
        retry = 86_400 if math.isinf(wait) else max(1, math.ceil(wait))
        return Denial(layer, kind, message, retry)

    def check_request(self, ip: str) -> Denial | None:
        """Layer 1. Every request to a limited route costs one token."""
        with self._lock:
            wait = self.requests.wait_for(ip, 1)
            if wait:
                return self._deny(
                    "rate", "rate_limited",
                    "Too many requests from your network in the last minute. "
                    f"Try again in {_humanize(wait)}.", wait)
            self.requests.take(ip, 1)
            return None

    def reserve_llm(self, ip: str, cost: int) -> Denial | None:
        """Layers 2 and 3: charge `cost` estimated LLM calls, or neither."""
        with self._lock:
            if not self.budget.has_room(cost):
                wait = self.budget.seconds_until_reset()
                return self._deny(
                    "budget", "quota_exhausted",
                    "The demo's daily language-model quota is used up. It resets "
                    f"at 00:00 UTC, in about {_humanize(wait)}.", wait)
            wait = self.allowance.wait_for(ip, cost)
            if wait:
                return self._deny(
                    "allowance", "rate_limited",
                    "Each visitor gets a limited number of language-model answers "
                    "a day, and yours has run out for now. It refills gradually: "
                    f"this one fits again in about {_humanize(wait)}.", wait)
            self.allowance.take(ip, cost)
            self.budget.spend(cost)
            return None

    def status(self) -> dict:
        with self._lock:
            return {
                "llm_budget_used": self.budget.used,
                "llm_budget_limit": self.budget.limit,
                "resets_in_seconds": self.budget.seconds_until_reset(),
                "denied_since_start": dict(self.denied),
            }
