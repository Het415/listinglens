"""Generate an executive brief for an ASIN.

Pulls the product's review summary, return-risk prediction, and (when
available) conversation analytics, then makes a single structured LLM call
(instructor + Groq, same pattern as the agent's synthesizer) to produce an
ExecutiveBrief. Also returns the raw KPI metrics so the UI can render tiles
without re-deriving them.
"""
from functools import lru_cache

from dotenv import load_dotenv

from src.llm_config import groq_client, reasoning_effort, resilient_call

from .schemas import ExecutiveBrief

load_dotenv()


@lru_cache(maxsize=1)
def _client():
    # Narrative quality matters here — runs on the flagship agent model.
    return groq_client()


BRIEF_SYSTEM_PROMPT = (
    "You are a senior analyst writing a one-page executive brief for a product "
    "leadership team. Be concise, quantified, and decision-oriented. Ground every "
    "claim in the metrics provided — do not invent numbers. Prioritize actions by "
    "business impact. Write for a VP who has 60 seconds.\n\n"
    "Rank the actions honestly: assign priority per action based on business "
    "impact and urgency, not uniformly. A list where everything is 'medium' "
    "is useless to a reader deciding what to do first — mark the one or two "
    "that matter most as 'high' and anything deferrable as 'low'."
)


def _gather_metrics(asin: str) -> dict:
    from backend.mcp_server.tools._loader import asin_summary
    from backend.mcp_server.tools import return_risk as rr

    summary = asin_summary(asin)
    raw = summary.get("raw_star_distribution") or {}
    metrics = {
        "asin": asin,
        # The model reads these keys, so they say what they are: the analysed
        # sample is 50 reviews per star, while the rating and the shares
        # describe every rating the product has. Under the old `total_reviews`
        # name, a brief could write "21% of the 250 reviews".
        "reviews_sampled": summary.get("total_reviews"),
        "ratings_total": sum(int(n) for n in raw.values()) or None,
        "sentiment_basis": (
            "avg_rating is the mean of all ratings_total ratings. pct_negative and "
            "pct_positive estimate the share of all reviews whose text reads as "
            "negative or positive: measured on reviews_sampled reviews (an equal "
            "number per star), then weighted to the real star mix."
        ),
        "avg_rating": summary.get("avg_rating"),
        "pct_negative": summary.get("pct_negative"),
        "pct_positive": summary.get("pct_positive"),
        "top_topics": [
            {"label": t.get("label"), "pct_negative": t.get("pct_negative"),
             "complaint_level": t.get("complaint_level")}
            for t in (summary.get("top_topics", []) or [])[:5]
        ],
    }
    try:
        risk = rr.predict_return_risk(asin)
        metrics["return_risk"] = {
            "risk_pct": risk.get("risk_pct"),
            "risk_label": risk.get("risk_label"),
        }
    except Exception:
        metrics["return_risk"] = None

    # Conversation analytics are optional (only present once precomputed).
    try:
        from backend.mcp_server.tools._loader import asin_conversation_summary
        conv = asin_conversation_summary(asin)
        metrics["conversations"] = {
            "n_conversations": conv.get("n_conversations"),
            "resolution_rate": conv.get("resolution_rate"),
            "escalation_rate": conv.get("escalation_rate"),
            "top_intents": list((conv.get("intent_distribution") or {}).items())[:3],
            "avg_sentiment_trajectory": conv.get("avg_sentiment_trajectory"),
        }
    except Exception:
        metrics["conversations"] = None
    return metrics


def _context_block(product_name: str, metrics: dict) -> str:
    import json
    return (
        f"Product: {product_name} (ASIN {metrics['asin']})\n"
        f"Metrics (JSON):\n{json.dumps(metrics, indent=2)}"
    )


def generate_brief(asin: str, product_name: str | None = None) -> dict:
    """Return {asin, product_name, metrics, brief}."""
    from backend.mcp_server.tools._loader import supported_asins
    product_name = product_name or supported_asins().get(asin, asin)

    metrics = _gather_metrics(asin)
    user_msg = (
        _context_block(product_name, metrics)
        + "\n\nWrite the executive brief now."
    )
    brief: ExecutiveBrief = resilient_call("agent", lambda model: _client().chat.completions.create(
        model=model,
        response_model=ExecutiveBrief,
        reasoning_effort=reasoning_effort("agent"),
        max_retries=2,
        messages=[
            {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    ))
    return {
        "asin": asin,
        "product_name": product_name,
        "metrics": metrics,
        "brief": brief.model_dump(),
    }
