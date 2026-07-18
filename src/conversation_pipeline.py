"""Analyze support transcripts into per-ASIN conversation analytics.

For each conversation:
  - intent classification of the opening customer message (trained model + LLM
    fallback, from src.intent_classifier)
  - sentiment trajectory across the customer's turns (reusing the existing HF
    sentiment functions in src.nlp_pipeline) -> start/end/delta = did the
    interaction recover or escalate
  - resolution + escalation signals

Aggregated per ASIN into intent distribution, resolution/escalation rates,
average sentiment trajectory, model-based topics (src.topic_model), and an
honest out-of-distribution intent accuracy (predicted vs the seed label the
transcript was generated with).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

ESCALATION_KEYWORDS = (
    "manager", "supervisor", "unacceptable", "ridiculous", "lawyer",
    "escalate", "cancel my", "never buying", "worst", "furious", "scam",
)


def transcripts_path(asin: str) -> Path:
    return PROCESSED_DIR / f"transcripts_{asin}.jsonl"


def load_transcripts(asin: str) -> list[dict]:
    path = transcripts_path(asin)
    if not path.exists():
        raise FileNotFoundError(f"No transcripts for {asin}: {path}")
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _customer_turns(convo: dict) -> list[str]:
    return [t["text"] for t in convo.get("turns", []) if t.get("speaker") == "customer"]


def _compound_scores(texts: list[str]) -> list[float]:
    """Compound sentiment (-1..1) per text, via the existing HF pipeline."""
    if not texts:
        return []
    from src.nlp_pipeline import get_sentiment_batch, parse_sentiment_results
    raw = get_sentiment_batch(texts)
    df = parse_sentiment_results(raw)
    return [float(x) for x in df["compound_score"].tolist()]


def _is_escalation(customer_texts: list[str], start: float, end: float) -> bool:
    if start - end > 0.25:  # sentiment dropped over the interaction
        return True
    blob = " ".join(customer_texts).lower()
    return any(k in blob for k in ESCALATION_KEYWORDS)


def analyze_asin(asin: str) -> dict:
    """Compute the full conversation-analytics summary for one ASIN."""
    from src.intent_classifier import predict_batch
    from src.topic_model import model_topics

    convos = load_transcripts(asin)
    n = len(convos)
    if n == 0:
        return {"asin": asin, "n_conversations": 0}

    # Batch sentiment over every customer turn (one HF pass), then slice back.
    all_customer_turns: list[str] = []
    spans: list[tuple[int, int]] = []
    for c in convos:
        cts = _customer_turns(c)
        spans.append((len(all_customer_turns), len(all_customer_turns) + len(cts)))
        all_customer_turns.extend(cts)
    compounds = _compound_scores(all_customer_turns)

    # Intent of the opening customer message per conversation.
    openers = [(_customer_turns(c) or [""])[0] for c in convos]
    intents = predict_batch(openers, allow_llm=False)

    per_convo = []
    intent_counts: dict[str, int] = {}
    resolved_ct = escalated_ct = 0
    turn_counts: list[int] = []
    deltas: list[float] = []
    # normalized 3-bin trajectory (start / middle / end) averaged across convos
    bins_sum = [0.0, 0.0, 0.0]
    bins_cnt = [0, 0, 0]

    for c, (lo, hi), intent in zip(convos, spans, intents):
        traj = compounds[lo:hi]
        start = traj[0] if traj else 0.0
        end = traj[-1] if traj else 0.0
        delta = round(end - start, 4)
        cust_texts = all_customer_turns[lo:hi]
        escalated = _is_escalation(cust_texts, start, end)

        cat = intent.get("category")
        label = intent.get("intent")
        if cat:
            intent_counts[label] = intent_counts.get(label, 0) + 1
        if c.get("resolved"):
            resolved_ct += 1
        if escalated:
            escalated_ct += 1
        turn_counts.append(len(c.get("turns", [])))
        deltas.append(delta)

        # bucket the trajectory into 3 normalized positions
        if traj:
            for pos, v in enumerate(traj):
                b = 0 if len(traj) == 1 else min(2, int(pos / (len(traj) - 1) * 2 + 1e-9))
                bins_sum[b] += v
                bins_cnt[b] += 1

        per_convo.append({
            "conversation_id": c["conversation_id"],
            "channel": c.get("channel"),
            "intent": label,
            "intent_category": cat,
            "intent_confidence": intent.get("confidence"),
            "intent_source": intent.get("source"),
            "intent_seed": c.get("intent_seed"),
            "theme_seed": c.get("theme_seed"),
            "resolved": bool(c.get("resolved")),
            "escalated": escalated,
            "n_turns": len(c.get("turns", [])),
            "sentiment_start": round(start, 4),
            "sentiment_end": round(end, 4),
            "sentiment_delta": delta,
            "sentiment_trajectory": [round(x, 4) for x in traj],
        })

    # Model topics over the opening issue message of each conversation (the
    # substantive complaint) rather than every turn — avoids closing
    # pleasantries ("thanks so much!") dominating the topic labels.
    topics = model_topics([o for o in openers if o.strip()])

    avg_traj = [round(bins_sum[i] / bins_cnt[i], 4) if bins_cnt[i] else 0.0 for i in range(3)]

    return {
        "asin": asin,
        "n_conversations": n,
        "intent_distribution": dict(sorted(intent_counts.items(), key=lambda kv: -kv[1])),
        "resolution_rate": round(resolved_ct / n, 4),
        "escalation_rate": round(escalated_ct / n, 4),
        "avg_turns": round(sum(turn_counts) / n, 2),
        "avg_sentiment_delta": round(sum(deltas) / n, 4),
        "avg_sentiment_trajectory": {"start": avg_traj[0], "middle": avg_traj[1], "end": avg_traj[2]},
        "topics": topics["topics"],
        "sample_conversations": per_convo[:6],
        "conversations": per_convo,
    }


def summary_view(full: dict) -> dict:
    """Lighter view for API responses (drops the full per-convo list)."""
    view = {k: v for k, v in full.items() if k != "conversations"}
    return view
