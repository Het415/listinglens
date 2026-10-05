"""Concurrent first callers must share ONE embedder (audit E-07).

`get_embeddings` was an `lru_cache`, which does not serialise a cold miss:
every caller that arrived before the first build finished built its own
~90 MiB ONNX session, and FAISS kept each copy for the life of the process.
Offline: the real class is swapped for a slow fake, so no model is loaded.
"""

from __future__ import annotations

import threading
import time

import src.onnx_embeddings as oe

CALLERS = 8


def test_concurrent_cold_callers_build_one_embedder(monkeypatch):
    built = []

    class SlowEmbeddings:
        def __init__(self):
            time.sleep(0.2)   # a cold ORT session takes seconds; any overlap shows the race
            built.append(self)

    monkeypatch.setattr(oe, "MiniLMOnnxEmbeddings", SlowEmbeddings)
    monkeypatch.setattr(oe, "_EMBEDDINGS", None)

    start = threading.Barrier(CALLERS)
    got = []

    def caller():
        start.wait()
        got.append(oe.get_embeddings())

    threads = [threading.Thread(target=caller) for _ in range(CALLERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(built) == 1
    assert len(got) == CALLERS and all(e is built[0] for e in got)


def test_a_warm_call_returns_the_same_instance(monkeypatch):
    monkeypatch.setattr(oe, "MiniLMOnnxEmbeddings", object)
    monkeypatch.setattr(oe, "_EMBEDDINGS", None)
    assert oe.get_embeddings() is oe.get_embeddings()
