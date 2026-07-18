"""Generate synthetic multi-turn support transcripts, one JSONL per ASIN.

    python -m scripts.generate_transcripts                 # all ASINs
    python -m scripts.generate_transcripts --asin B07GZFM1ZM --n 12 --force

Each conversation is seeded with:
  - an **intent** drawn from the Bitext taxonomy (why the customer contacted —
    the transactional ask the trained classifier is scored against), and
  - a **theme** drawn from the product's REAL top complaint topics
    (features_{asin}.json), woven into the narrative.

The seed intent records what the conversation was generated around (kept for
provenance); it is not treated as clean single-label ground truth, since a
support message often reads as several intents at once.
Output: data/processed/transcripts_{asin}.jsonl
"""
import argparse
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "processed"

# Support-relevant subset of the Bitext taxonomy, weighted toward what shows up
# in product support. Keys are Bitext `category` codes (the classifier's labels).
INTENT_WEIGHTS = {
    "REFUND": 5, "ORDER": 3, "CANCEL": 3, "DELIVERY": 4, "SHIPPING": 3,
    "CONTACT": 2, "PAYMENT": 2, "ACCOUNT": 2, "FEEDBACK": 4, "INVOICE": 1,
}


def _model() -> str:
    return os.getenv("INTENT_LLM_MODEL", "llama-3.1-8b-instant")


class Turn(BaseModel):
    speaker: str = Field(description="'customer' or 'agent'")
    text: str = Field(description="What this speaker says.")


class GeneratedConversation(BaseModel):
    turns: list[Turn] = Field(description="4-7 turns, alternating, starting with the customer.")
    resolved: bool = Field(description="Was the customer's issue resolved by the end?")


def _client():
    import instructor
    from groq import Groq
    return instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))


def _themes_for(asin: str) -> list[str]:
    """Real top complaint topics for the product, from precomputed features."""
    from backend.mcp_server.tools._loader import asin_summary
    try:
        summary = asin_summary(asin)
    except Exception:
        return ["general product experience"]
    topics = summary.get("top_topics", []) or []
    labels = [t.get("label") for t in topics if t.get("label")]
    return labels or ["general product experience"]


def _intent_label(category: str) -> str:
    from src.intent_classifier import label_for
    return label_for(category)


def _gen_one(client, product: str, category: str, theme: str) -> GeneratedConversation | None:
    system = (
        "You write realistic customer-support chat transcripts. Output a natural "
        "multi-turn conversation between a 'customer' and a support 'agent'. "
        "4-7 turns, alternating, starting with the customer. Keep it concise and "
        "human — include the customer's emotional arc (frustration, relief, etc.)."
    )
    user = (
        f"Product: {product}\n"
        f"Customer's core intent: {_intent_label(category)} ({category})\n"
        f"Weave in this specific product issue: {theme}\n"
        "Write the conversation and decide realistically whether it was resolved."
    )
    try:
        return client.chat.completions.create(
            model=_model(),
            response_model=GeneratedConversation,
            max_retries=2,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
    except Exception as e:  # noqa: BLE001
        print(f"    ! generation failed ({type(e).__name__}: {e})")
        return None


def _generate_for_asin(client, asin: str, product: str, n: int, rng: random.Random) -> list[dict]:
    themes = _themes_for(asin)
    categories = list(INTENT_WEIGHTS.keys())
    weights = list(INTENT_WEIGHTS.values())
    now = datetime.now(timezone.utc)
    convos: list[dict] = []
    for i in range(n):
        category = rng.choices(categories, weights=weights, k=1)[0]
        theme = rng.choice(themes)
        gen = _gen_one(client, product, category, theme)
        if gen is None or not gen.turns:
            continue
        created = now - timedelta(days=rng.randint(0, 89), hours=rng.randint(0, 23))
        convos.append({
            "conversation_id": f"{asin}-conv-{i:03d}",
            "asin": asin,
            "channel": rng.choice(["chat", "email", "phone"]),
            "created_at": created.isoformat(),
            "intent_seed": category,          # ground-truth intent label
            "theme_seed": theme,
            "resolved": bool(gen.resolved),
            "turns": [
                {"turn": t_i, "speaker": ("customer" if t.speaker.lower().startswith("c") else "agent"),
                 "text": t.text}
                for t_i, t in enumerate(gen.turns)
            ],
        })
        time.sleep(0.2)  # be gentle on the Groq rate limit
    return convos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asin", default=None, help="Only this ASIN (default: all supported)")
    ap.add_argument("--n", type=int, default=12, help="Conversations per ASIN")
    ap.add_argument("--force", action="store_true", help="Regenerate even if file exists")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from src.ingest import SUPPORTED_ASINS
    targets = {args.asin: SUPPORTED_ASINS.get(args.asin, args.asin)} if args.asin else dict(SUPPORTED_ASINS)

    client = _client()
    rng = random.Random(args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for asin, product in targets.items():
        out_path = OUT_DIR / f"transcripts_{asin}.jsonl"
        if out_path.exists() and not args.force:
            print(f"• {asin} ({product}): exists, skipping (use --force)")
            continue
        print(f"• {asin} ({product}): generating {args.n} conversations ...")
        convos = _generate_for_asin(client, asin, product, args.n, rng)
        with open(out_path, "w") as f:
            for c in convos:
                f.write(json.dumps(c) + "\n")
        print(f"  -> wrote {len(convos)} -> {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
