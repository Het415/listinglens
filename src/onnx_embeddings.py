"""Torch-free MiniLM embeddings for the RAG path.

Why this exists
---------------
`_get_embeddings` used to return `langchain_huggingface.HuggingFaceEmbeddings`,
which loads sentence-transformers, which loads torch. Measured inside the
production image, that import chain costs ~490MiB of RSS *before any model
weights are read*:

    import torch                  +212 MiB
    import sentence_transformers  +276 MiB
    MiniLM weights                 +87 MiB
    one embed_query                +49 MiB   -> 705 MiB total

The model is the cheap part. The frameworks are the expensive part, and the
only thing the app ever asked them to do was `SentenceTransformer(...)` plus
`.encode(...)`. So this module does that arithmetic directly against the ONNX
export of the same checkpoint: onnxruntime + tokenizers, no torch anywhere.
Same process measured the same way lands around 265 MiB.

all-MiniLM-L6-v2 is three steps — Transformer, mean-pool over the attention
mask, L2-normalize — so "reimplementing" it is the six lines in `_encode`.

Vector compatibility
--------------------
This MUST produce the same vectors as whatever built the FAISS indexes in
data/processed/vectorstore_*/, or similarity search silently degrades instead
of failing loudly. It does: re-embedding stored documents and comparing against
`index.reconstruct(pos)` gives cosine 1.000000 (max observed drift 1.19e-07,
which is float32 rounding). `tests/test_onnx_embeddings.py` asserts this, so a
regression here fails CI rather than quietly returning worse answers.

`_REVISION` is pinned deliberately. An unpinned re-export of the ONNX graph on
the Hub would change vectors under us with no signal at all — the committed
indexes are the contract, so the model revision has to be part of it.
"""

from __future__ import annotations

import os
from functools import lru_cache

import numpy as np
from langchain_core.embeddings import Embeddings

_REPO_ID = "sentence-transformers/all-MiniLM-L6-v2"
# Pinned so a Hub re-export cannot silently invalidate the committed indexes.
_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
# all-MiniLM-L6-v2 ships max_seq_length=256; sentence-transformers truncates
# there, so we must too or long chunks would embed differently.
_MAX_SEQ_LEN = 256
# Chunks are ~300 chars, so batches stay small; this is about bounding peak RSS
# on a memory-capped instance, not throughput.
_BATCH_SIZE = 32


class MiniLMOnnxEmbeddings(Embeddings):
    """LangChain `Embeddings` backed by onnxruntime instead of torch."""

    def __init__(self) -> None:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        import onnxruntime as ort

        model_path = hf_hub_download(_REPO_ID, "onnx/model.onnx", revision=_REVISION)
        tok_path = hf_hub_download(_REPO_ID, "tokenizer.json", revision=_REVISION)

        self._tokenizer = Tokenizer.from_file(tok_path)
        self._tokenizer.enable_truncation(max_length=_MAX_SEQ_LEN)
        self._tokenizer.enable_padding()

        # Single-threaded: the free-tier instance has one core to spare, and
        # extra ORT threads cost arenas we can't afford.
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = int(os.getenv("ONNX_NUM_THREADS", "1"))
        opts.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            model_path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}

    def _encode(self, texts: list[str]) -> np.ndarray:
        encoded = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)

        feed = {"input_ids": ids, "attention_mask": mask}
        # BERT-family exports take token_type_ids; guard in case a future
        # revision drops the input rather than failing on an unexpected key.
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.array(
                [e.type_ids for e in encoded], dtype=np.int64
            )

        token_embeddings = self._session.run(None, feed)[0]  # (batch, seq, 384)

        # Mean-pool over real tokens only — padding must not dilute the mean.
        m = mask[..., None].astype(np.float32)
        pooled = (token_embeddings * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        # L2-normalize, so FAISS L2 distance ranks the same as cosine.
        return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = [t.replace("\n", " ") for t in texts[start : start + _BATCH_SIZE]]
            out.extend(self._encode(batch).tolist())
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text.replace("\n", " ")])[0].tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> MiniLMOnnxEmbeddings:
    """Process-wide singleton.

    The ORT session and tokenizer are the expensive part; every ASIN's
    vectorstore shares one instance. Keeping this an `lru_cache` preserves the
    behaviour the previous torch-backed `_get_embeddings` had.
    """
    return MiniLMOnnxEmbeddings()
