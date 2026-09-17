"""Guards the contract between the embedding model and the committed FAISS indexes.

The indexes in data/processed/vectorstore_*/ are committed artefacts. If the
embedding model ever stops producing the vectors they were built from, nothing
raises — similarity search just quietly returns worse neighbours. That failure
mode is why this test compares against vectors pulled straight out of the index
rather than asserting on search results, which look plausible either way.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VECTORSTORE_DIR = REPO_ROOT / "data" / "processed"
# Small, fast subset. The full 12-store sweep lives in the handoff notes.
SAMPLE_ASINS = ["B08XPWDSWW", "B00N2ZDXW2"]
EXPECTED_DIM = 384


def _load_index(asin: str):
    faiss = pytest.importorskip("faiss")
    d = VECTORSTORE_DIR / f"vectorstore_{asin}"
    if not (d / "index.faiss").exists():
        pytest.skip(f"vectorstore for {asin} not present")
    index = faiss.read_index(str(d / "index.faiss"))
    with open(d / "index.pkl", "rb") as fh:
        docstore, index_to_id = pickle.load(fh)
    return index, docstore, index_to_id


@pytest.fixture(scope="module")
def embeddings():
    pytest.importorskip("onnxruntime")
    from src.onnx_embeddings import get_embeddings

    return get_embeddings()


def test_embedding_dimension(embeddings):
    assert len(embeddings.embed_query("battery life")) == EXPECTED_DIM


def test_query_vectors_are_l2_normalised(embeddings):
    v = np.asarray(embeddings.embed_query("sound quality is poor"), dtype=np.float32)
    assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)


def test_batch_matches_single(embeddings):
    """embed_documents must agree with embed_query — batching/padding must not shift
    a vector, which is the subtle way a mean-pool bug shows up."""
    texts = ["short one", "a considerably longer passage about battery life and fit"]
    batch = np.asarray(embeddings.embed_documents(texts), dtype=np.float32)
    for i, t in enumerate(texts):
        single = np.asarray(embeddings.embed_query(t), dtype=np.float32)
        assert float(batch[i] @ single) > 0.9999


@pytest.mark.parametrize("asin", SAMPLE_ASINS)
def test_reproduces_committed_index_vectors(embeddings, asin):
    """The load-bearing assertion: re-embedding a stored document must reproduce
    the vector already sitting in the committed index."""
    index, docstore, index_to_id = _load_index(asin)
    assert index.d == EXPECTED_DIM

    positions = [0, index.ntotal // 2, index.ntotal - 1]
    for pos in positions:
        stored = np.asarray(index.reconstruct(int(pos)), dtype=np.float32)
        text = docstore.search(index_to_id[pos]).page_content
        fresh = np.asarray(embeddings.embed_query(text), dtype=np.float32)
        cosine = float(
            stored @ fresh / (np.linalg.norm(stored) * np.linalg.norm(fresh))
        )
        assert cosine > 0.9999, (
            f"{asin}[{pos}] drifted from the committed index (cosine={cosine:.6f}). "
            "The embedding model no longer matches these vectors — either revert the "
            "model change or rebuild every data/processed/vectorstore_*/."
        )


def test_no_torch_in_the_embedding_path(embeddings):
    """torch costs ~490MiB of RSS and is the reason this module exists. If it
    creeps back into the import graph, the memory win is gone."""
    import sys

    embeddings.embed_query("warm the model")
    assert "torch" not in sys.modules
    assert "sentence_transformers" not in sys.modules
