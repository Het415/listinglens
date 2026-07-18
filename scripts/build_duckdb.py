"""Build the analytical DuckDB warehouse from the precomputed artifacts.

    python -m scripts.build_duckdb

Loads everything in data/processed/ into data/processed/listinglens.duckdb:

  reviews             one row per review (+ asin)          <- nlp_{asin}.csv
  product_metrics     one row per product (flat KPIs)      <- features_{asin}.json summary
  product_summary     one row per product (summary JSON)   <- features_{asin}.json summary
  product_features    one row per product (features JSON)  <- features_{asin}.json features
  topics              exploded review topics per product   <- summary.top_topics
  conversations       one row per support conversation     <- conversations_{asin}.json
  conversation_turns  one row per turn                     <- transcripts_{asin}.jsonl
  conversation_intents intent counts per product           <- derived

The DB is the substrate for notebooks/eda.ipynb and (optionally) the runtime
loader. It is rebuilt from files, so it is safe to delete and regenerate.
"""
import json
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "processed"
DB_PATH = PROCESSED / "listinglens.duckdb"


def _asins_with_features() -> list[str]:
    return sorted(p.stem.replace("features_", "") for p in PROCESSED.glob("features_*.json"))


def _load_reviews() -> pd.DataFrame:
    frames = []
    for csv in sorted(PROCESSED.glob("nlp_*.csv")):
        asin = csv.stem.replace("nlp_", "")
        df = pd.read_csv(csv)
        df.insert(0, "asin", asin)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load_products():
    metrics, summaries, features, topics = [], [], [], []
    for asin in _asins_with_features():
        blob = json.loads((PROCESSED / f"features_{asin}.json").read_text())
        summ = blob.get("summary", {}) or {}
        feats = blob.get("features", {}) or {}
        summaries.append({"asin": asin, "summary_json": json.dumps(summ)})
        features.append({"asin": asin, "features_json": json.dumps(feats)})
        metrics.append({
            "asin": asin,
            "total_reviews": summ.get("total_reviews"),
            "avg_rating": summ.get("avg_rating"),
            "pct_negative": summ.get("pct_negative"),
            "pct_positive": summ.get("pct_positive"),
            "n_topics": feats.get("n_topics"),
            "avg_compound_score": feats.get("avg_compound_score"),
        })
        for t in summ.get("top_topics", []) or []:
            topics.append({
                "asin": asin,
                "label": t.get("label"),
                "keywords": ", ".join(t.get("keywords", []) or []),
                "count": t.get("count"),
                "pct_negative": t.get("pct_negative"),
                "pct_positive": t.get("pct_positive"),
                "complaint_level": t.get("complaint_level"),
            })
    return (pd.DataFrame(metrics), pd.DataFrame(summaries),
            pd.DataFrame(features), pd.DataFrame(topics))


def _load_conversations():
    convos, turns, intents = [], [], []
    for jf in sorted(PROCESSED.glob("conversations_*.json")):
        asin = jf.stem.replace("conversations_", "")
        blob = json.loads(jf.read_text())
        for c in blob.get("conversations", []) or []:
            convos.append({
                "asin": asin,
                "conversation_id": c.get("conversation_id"),
                "channel": c.get("channel"),
                "intent": c.get("intent"),
                "intent_category": c.get("intent_category"),
                "intent_seed": c.get("intent_seed"),
                "intent_confidence": c.get("intent_confidence"),
                "intent_source": c.get("intent_source"),
                "resolved": c.get("resolved"),
                "escalated": c.get("escalated"),
                "n_turns": c.get("n_turns"),
                "sentiment_start": c.get("sentiment_start"),
                "sentiment_end": c.get("sentiment_end"),
                "sentiment_delta": c.get("sentiment_delta"),
            })
        for label, cnt in (blob.get("intent_distribution", {}) or {}).items():
            intents.append({"asin": asin, "intent": label, "count": cnt})
    for tf in sorted(PROCESSED.glob("transcripts_*.jsonl")):
        asin = tf.stem.replace("transcripts_", "")
        for line in tf.read_text().splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            for t in c.get("turns", []) or []:
                turns.append({
                    "asin": asin,
                    "conversation_id": c.get("conversation_id"),
                    "turn": t.get("turn"),
                    "speaker": t.get("speaker"),
                    "text": t.get("text"),
                })
    return pd.DataFrame(convos), pd.DataFrame(turns), pd.DataFrame(intents)


def _write(con, name: str, df: pd.DataFrame) -> None:
    con.execute(f"DROP TABLE IF EXISTS {name}")
    if df.empty:
        return
    con.register("_tmp", df)
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM _tmp")
    con.unregister("_tmp")
    print(f"  {name}: {len(df):,} rows")


def main() -> int:
    print(f"Building {DB_PATH.relative_to(REPO_ROOT)} ...")
    reviews = _load_reviews()
    metrics, summaries, features, topics = _load_products()
    convos, turns, intents = _load_conversations()

    con = duckdb.connect(str(DB_PATH))
    try:
        _write(con, "reviews", reviews)
        _write(con, "product_metrics", metrics)
        _write(con, "product_summary", summaries)
        _write(con, "product_features", features)
        _write(con, "topics", topics)
        _write(con, "conversations", convos)
        _write(con, "conversation_turns", turns)
        _write(con, "conversation_intents", intents)
    finally:
        con.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
