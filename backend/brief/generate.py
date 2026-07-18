"""Generate an executive brief for an ASIN.

Pulls the product's review summary, return-risk prediction, and (when
available) conversation analytics, then makes a single structured LLM call
(instructor + Groq, same pattern as the agent's synthesizer) to produce an
ExecutiveBrief. Also returns the raw KPI metrics so the UI can render tiles
without re-deriving them.
"""
import os
from functools import lru_cache

from dotenv import load_dotenv

from .schemas import ExecutiveBrief

load_dotenv()


def _model() -> str:
    # Narrative quality matters here — use the flagship agent model.
    return os.getenv("AGENT_MODEL", "llama-3.3-70b-versatile")


@lru_cache(maxsize=1)
def _client():
    import instructor
    from groq import Groq
    return instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))


BRIEF_SYSTEM_PROMPT = (
    "You are a senior analyst writing a one-page executive brief for a product "
    "leadership team. Be concise, quantified, and decision-oriented. Ground every "
    "claim in the metrics provided — do not invent numbers. Prioritize actions by "
    "business impact. Write for a VP who has 60 seconds."
)


def _gather_metrics(asin: str) -> dict:
    from backend.mcp_server.tools._loader import asin_summary
    from backend.mcp_server.tools import return_risk as rr

    summary = asin_summary(asin)
    metrics = {
        "asin": asin,
        "total_reviews": summary.get("total_reviews"),
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
    brief: ExecutiveBrief = _client().chat.completions.create(
        model=_model(),
        response_model=ExecutiveBrief,
        max_retries=2,
        messages=[
            {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    return {
        "asin": asin,
        "product_name": product_name,
        "metrics": metrics,
        "brief": brief.model_dump(),
    }
