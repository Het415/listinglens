"""Lightweight embeddings-based topic modeling ("mini-BERTopic").

Upgrades the keyword-substring theme detection in src/nlp_pipeline.py
(CATEGORY_KEYWORDS) to a genuine model-based approach, using only deps the
project already ships:

    MiniLM sentence embeddings  ->  KMeans clustering  ->  c-TF-IDF top terms

c-TF-IDF (class-based TF-IDF, the idea behind BERTopic's labels) treats each
cluster as one document and scores terms by how distinctive they are to that
cluster, giving human-readable topic labels without LDA's bag-of-words
assumptions. Returns per-topic keywords, size, and the doc->topic assignment.
"""
from __future__ import annotations

import re

import numpy as np


def _embed(texts: list[str]) -> np.ndarray:
    """Embed texts with the shared MiniLM singleton used by the RAG layer."""
    from src.rag_chatbot import _get_embeddings
    emb = _get_embeddings()
    vecs = emb.embed_documents(list(texts))
    return np.asarray(vecs, dtype=np.float32)


def _ctfidf_terms(docs: list[str], labels: np.ndarray, n_topics: int,
                  top_n: int = 8) -> dict[int, list[str]]:
    """Top distinctive terms per cluster via class-based TF-IDF."""
    from sklearn.feature_extraction.text import CountVectorizer

    # One "document" per cluster = concatenation of its member docs.
    grouped = ["" for _ in range(n_topics)]
    for doc, lab in zip(docs, labels):
        grouped[int(lab)] += " " + doc

    cv = CountVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    counts = cv.fit_transform(grouped)            # (n_topics x vocab)
    vocab = np.array(cv.get_feature_names_out())

    tf = counts.toarray().astype(float)
    tf_sum = tf.sum(axis=1, keepdims=True)
    tf_sum[tf_sum == 0] = 1.0
    tf_norm = tf / tf_sum                          # term freq within cluster
    # inverse cluster frequency: down-weight terms common to many clusters
    df = (tf > 0).sum(axis=0)
    icf = np.log(1.0 + (n_topics / np.maximum(df, 1)))
    scores = tf_norm * icf

    out: dict[int, list[str]] = {}
    for k in range(n_topics):
        order = np.argsort(scores[k])[::-1]
        terms = [t for t in vocab[order] if not re.fullmatch(r"\d+", t)][:top_n]
        out[k] = terms
    return out


def model_topics(docs: list[str], n_topics: int | None = None,
                 top_n: int = 8, random_state: int = 42) -> dict:
    """Cluster docs into topics and label each with distinctive terms.

    Returns:
        {
          "n_topics": int,
          "assignments": [topic_id per doc],
          "topics": [{"topic_id", "label", "keywords", "size", "share"}]
        }
    """
    docs = [str(d or "").strip() for d in docs]
    docs = [d for d in docs if d]
    n = len(docs)
    if n == 0:
        return {"n_topics": 0, "assignments": [], "topics": []}

    # Heuristic topic count: ~1 topic per 12 docs, clamped to [2, 8].
    if n_topics is None:
        n_topics = max(2, min(8, n // 12 or 2))
    n_topics = min(n_topics, n)

    from sklearn.cluster import KMeans

    vecs = _embed(docs)
    km = KMeans(n_clusters=n_topics, random_state=random_state, n_init=10)
    labels = km.fit_predict(vecs)

    terms = _ctfidf_terms(docs, labels, n_topics, top_n=top_n)
    sizes = np.bincount(labels, minlength=n_topics)

    topics = []
    for k in range(n_topics):
        kws = terms.get(k, [])
        topics.append({
            "topic_id": k,
            "label": ", ".join(kws[:3]) if kws else f"Topic {k}",
            "keywords": kws,
            "size": int(sizes[k]),
            "share": round(float(sizes[k]) / n, 4),
        })
    topics.sort(key=lambda t: t["size"], reverse=True)

    return {
        "n_topics": n_topics,
        "assignments": [int(x) for x in labels],
        "topics": topics,
    }
