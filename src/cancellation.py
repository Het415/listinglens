"""
Cooperative cancellation for the long-running analysis pipeline.

Why this exists — the short version: nothing else works.

`POST /analyze` can run for 3-5 minutes. When the user switches products the
browser aborts the request, and we want the backend to stop too. Two things
that look like they would deliver that do not:

  1. Making the handler `async def` is not enough. Starlette does not raise
     `CancelledError` in a request handler when the client goes away — a
     handler that awaits in a loop runs to completion regardless. The only
     reliable signal is polling `Request.is_disconnected()`.
  2. Running the work via `asyncio.to_thread` and cancelling the await is not
     enough either. Python cannot kill a thread; cancelling the await abandons
     the *waiting*, and the worker thread keeps burning CPU to completion.

So cancellation has to be cooperative: the caller sets a flag, and the pipeline
checks it at points where stopping is safe. `get_sentiment_batch` is the one
that matters — it is a per-review loop, so a check per iteration cancels within
a single review.
"""

import threading


class AnalysisCancelled(Exception):
    """
    Raised inside a pipeline worker thread when the caller has gone away.

    Not an error condition: the expected outcome is that the partial work is
    discarded and nothing is written to disk or the cache.
    """


class CancelToken:
    """
    A thread-safe "stop when you can" flag shared between the request handler
    (event loop) and the pipeline (worker thread).

    Built on `threading.Event` rather than a bare bool so `sleep()` can wake
    the instant cancellation arrives instead of finishing its nap first — the
    pipeline's 503 backoff waits 20s, and sitting through that after the client
    has left would defeat the point.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. Safe to call from any thread, and idempotent."""
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise `AnalysisCancelled` if cancellation has been requested."""
        if self._event.is_set():
            raise AnalysisCancelled()

    def sleep(self, seconds: float) -> None:
        """
        Interruptible `time.sleep`. Returns normally after `seconds`, or raises
        `AnalysisCancelled` immediately if cancelled while waiting.
        """
        if self._event.wait(seconds):
            raise AnalysisCancelled()


# ── None-tolerant helpers ──────────────────────────────────────────────────────
# Every pipeline entry point takes `cancel: CancelToken | None = None` so the
# many callers that have no cancellation story (preload_cache, /chat, the
# precompute script, the tests) keep working untouched. These two helpers keep
# the call sites free of `if cancel is not None` noise.

def check_cancelled(cancel: "CancelToken | None") -> None:
    if cancel is not None:
        cancel.check()


def cancellable_sleep(cancel: "CancelToken | None", seconds: float) -> None:
    if cancel is None:
        import time
        time.sleep(seconds)
    else:
        cancel.sleep(seconds)
