"""Rebuild the cached features_*.json offline from the committed nlp_*.csv.

    python -m scripts.recompute_features             # all ASINs with a CSV
    python -m scripts.recompute_features --asin B08XPWDSWW
    python -m scripts.recompute_features --dry-run   # print, write nothing

Why this exists: the cached analyses were written by older pipeline code, and
two fixes change what that code computes (audit T-08, T-09):
  - rating_avg from the real star distribution, one shared rating-sentiment
    gap, and four noise features dropped (src/features.py);
  - keyword categories matched on word boundaries, not substrings.

Re-running the whole NLP pipeline would re-score every review through the HF
sentiment API. It doesn't need to: nlp_{asin}.csv already holds each review's
sentiment columns, and features_{asin}.json already holds the real star
distribution (ingest captures it before balancing). So this feeds those two
through src.nlp_pipeline.analyze_scored_reviews, the same code the live
pipeline runs after sentiment, and the cache matches a fresh analysis.

Writes, atomically:
  - data/processed/features_{asin}.json: `features` and `summary` rebuilt,
    same single-line format app.py writes;
  - data/processed/nlp_{asin}.csv: only the `topic_id` column, and only when
    the category rules assign a review differently. Every other field is
    copied through byte for byte, so the diff is exactly the reassigned rows.

No network, no LLM, no HF.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8", newline="")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _rewrite_topic_ids(csv_path: Path, topic_ids: list[int], dry_run: bool) -> int:
    """Replace the topic_id column in place; return how many rows changed.

    Uses the csv module on raw strings rather than pandas, so floats and text
    are not re-serialised: pandas would rewrite every row's formatting.
    """
    raw = csv_path.read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(raw, newline="")))
    header, body = rows[0], rows[1:]
    if len(body) != len(topic_ids):
        raise ValueError(f"{csv_path.name}: {len(body)} rows but {len(topic_ids)} topic ids")
    col = header.index("topic_id")

    changed = 0
    for row, tid in zip(body, topic_ids):
        if row[col] != str(tid):
            row[col] = str(tid)
            changed += 1

    if changed and not dry_run:
        out = io.StringIO(newline="")
        # pandas' to_csv defaults: minimal quoting and "\n" line endings.
        csv.writer(out, lineterminator="\n").writerows([header, *body])
        _atomic_write_text(csv_path, out.getvalue())
    return changed


def recompute(asin: str, dry_run: bool = False) -> dict:
    import pandas as pd

    from src.nlp_pipeline import analyze_scored_reviews

    feat_path = PROCESSED_DIR / f"features_{asin}.json"
    csv_path = PROCESSED_DIR / f"nlp_{asin}.csv"
    old = json.loads(feat_path.read_text())
    raw_distribution = old["summary"]["raw_star_distribution"]

    df = pd.read_csv(csv_path)
    with redirect_stdout(io.StringIO()):  # the pipeline's progress prints
        result = analyze_scored_reviews(df, raw_distribution)
    new = {"features": result["features"], "summary": result["summary"]}

    topic_ids = [int(t) for t in result["df_enriched"]["topic_id"]]
    reassigned = _rewrite_topic_ids(csv_path, topic_ids, dry_run)
    if not dry_run:
        _atomic_write_text(feat_path, json.dumps(new))
    return {"asin": asin, "old": old, "new": new, "reassigned": reassigned}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asin", default=None, help="Only this ASIN (default: all with an nlp CSV)")
    ap.add_argument("--dry-run", action="store_true", help="Print the changes, write nothing")
    args = ap.parse_args()

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    asins = [args.asin] if args.asin else sorted(
        p.stem.replace("nlp_", "") for p in PROCESSED_DIR.glob("nlp_*.csv")
        if (PROCESSED_DIR / f"features_{p.stem.replace('nlp_', '')}.json").exists()
    )
    print(f"{'asin':<12} {'rating_avg':>16} {'gap':>16} {'top topic (count)':<34} reassigned")
    for asin in asins:
        r = recompute(asin, dry_run=args.dry_run)
        of, nf = r["old"]["features"], r["new"]["features"]
        top = r["new"]["summary"]["top_topics"][:1]
        top_s = f"{top[0]['label']} ({top[0]['count']})" if top else "-"
        print(f"{asin:<12} {of['rating_avg']:>6.2f} -> {nf['rating_avg']:<6.2f} "
              f"{of['rating_sentiment_gap']:>6.3f} -> {nf['rating_sentiment_gap']:<6.3f} "
              f"{top_s:<34} {r['reassigned']}")
    if args.dry_run:
        print("(dry run: nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
