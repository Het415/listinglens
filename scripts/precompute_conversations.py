"""Precompute per-ASIN conversation analytics from generated transcripts.

    python -m scripts.precompute_conversations                # all with transcripts
    python -m scripts.precompute_conversations --asin B08XPWDSWW

Reads data/processed/transcripts_{asin}.jsonl, runs src.conversation_pipeline,
and writes data/processed/conversations_{asin}.json.
"""
import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asin", default=None, help="Only this ASIN (default: all with transcripts)")
    args = ap.parse_args()

    from src.conversation_pipeline import analyze_asin

    if args.asin:
        asins = [args.asin]
    else:
        asins = sorted(p.stem.replace("transcripts_", "")
                       for p in PROCESSED_DIR.glob("transcripts_*.jsonl"))
    if not asins:
        print("No transcripts found. Run scripts.generate_transcripts first.")
        return 1

    for asin in asins:
        print(f"• {asin}: analyzing ...", flush=True)
        full = analyze_asin(asin)
        out = PROCESSED_DIR / f"conversations_{asin}.json"
        out.write_text(json.dumps(full, indent=2))
        print(f"  n={full.get('n_conversations', 0)}  "
              f"resolution={full.get('resolution_rate')}  "
              f"escalation={full.get('escalation_rate')}  "
              f"-> {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
