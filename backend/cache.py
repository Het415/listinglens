"""Redis-backed SSE cache for the agent/assistant streaming endpoints.

Why this lives here
-------------------
`/agent/query` and `/assistant/query` are the only endpoints that hit
Groq on every request — `/analyze` and `/chat` are already served from
on-disk caches (data/processed/*.csv + features_*.json) and the in-
memory `app_state`. So Groq spend and tail latency are concentrated on
exactly those two endpoints. Caching their SSE event sequences by
(asin, query, mode) gives repeat questions a sub-100ms replay path with
zero LLM cost.

Why we cache raw SSE chunks (strings) instead of dict events
-------------------------------------------------------------
The endpoints in app.py already serialize events to SSE wire format
(`event: x\ndata: {...}\n\n`). Wrapping at the post-serialization layer
means we don't have to refactor either endpoint's internal generator —
the wrapper takes whatever string-yielding generator the endpoint
already produces and just buffers + replays it.

Failure semantics
-----------------
Redis unavailable, REDIS_URL unset, redis package missing — all degrade
to passthrough. The endpoints work, nothing is cached, no exceptions
bubble. This is intentional: the Render production deploy doesn't have
Redis yet, and we don't want adding this module to break that surface.
Error events (`event: error`) are not cached — we don't want to memoize
transient Groq failures.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import AsyncIterator, Optional

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # redis pkg not installed — pure passthrough mode
    Redis = None  # type: ignore[assignment, misc]

    class RedisError(Exception):  # type: ignore[no-redef]
        pass


_DEFAULT_TTL = int(os.getenv("AGENT_CACHE_TTL", "3600"))  # seconds


def _get_client() -> Optional["Redis"]:
    """Returns a connected Redis client or None.

    Connect timeouts are tight (1s) on purpose — if Redis is misbehaving
    we'd rather skip the cache than block the request.
    """
    url = os.getenv("REDIS_URL")
    if not url or Redis is None:
        return None
    try:
        client = Redis.from_url(
            url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=False,
        )
        client.ping()
        return client
    except RedisError:
        return None
    except Exception:
        # Defensive: never let cache infra take down the request.
        return None


def make_key(asin: str, query: str, mode: str = "default") -> str:
    """Cache key for an agent invocation.

    SHA256 (not MD5) because (a) we want collision resistance over
    speed at this scale, and (b) the FIPS-disabled hosts in some CI
    images choke on md5.
    """
    raw = f"{asin}|{mode}|{query}".encode("utf-8")
    return f"agent:v1:{hashlib.sha256(raw).hexdigest()}"


async def cached_sse_stream(
    key: str,
    upstream: AsyncIterator[str],
    ttl: int = _DEFAULT_TTL,
) -> AsyncIterator[str]:
    """Read-through cache around an SSE-string generator.

    Cache hit  → yields stored chunks immediately, upstream never runs.
    Cache miss → yields upstream chunks live while buffering them; on
                 clean completion, persists buffer under `key`.
    Errored stream (any chunk contains `event: error`) → not cached.

    The yielded type is unchanged (`str`), so callers can hand the
    result straight to StreamingResponse with no shape changes.
    """
    client = _get_client()

    # Read path
    if client is not None:
        try:
            blob = client.get(key)
            if blob:
                chunks = json.loads(blob)
                for chunk in chunks:
                    yield chunk
                return
        except (RedisError, json.JSONDecodeError, TypeError):
            # Cache poisoned or transport failed — fall through to live.
            pass

    # Write path
    buffer: list[str] = []
    errored = False
    async for chunk in upstream:
        buffer.append(chunk)
        yield chunk
        if "event: error" in chunk:
            errored = True

    if client is not None and buffer and not errored:
        try:
            client.setex(key, ttl, json.dumps(buffer))
        except RedisError:
            pass
        except Exception:
            pass
