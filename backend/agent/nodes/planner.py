"""Planner node — classifies the query and proposes the initial tool sequence.

One LLM call via instructor + Groq, returning a structured Plan object.
Falls back to a sensible default plan if the structured call fails.
"""
import os

import instructor
from groq import Groq
from langchain_core.messages import AIMessage

from ..prompts import PLANNER_SYSTEM_PROMPT
from ..schemas import AgentState, Plan


def _model() -> str:
    return os.getenv("AGENT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


def _fallback_plan(query: str) -> Plan:
    """Cheap keyword-based fallback used if the LLM plan call fails."""
    q = query.lower()
    if any(w in q for w in ("launch", "variant", "new sku", "add a")):
        return Plan(
            query_type="launch",
            tool_sequence=["competitor_search", "trend_signal", "price_history", "review_qa"],
            rationale="Fallback plan for launch-type query",
        )
    if any(w in q for w in ("return", "spik", "churn", "unhappy", "complaint", "bad review")):
        return Plan(
            query_type="returns",
            tool_sequence=["predict_return_risk", "review_qa"],
            rationale="Fallback plan for returns/diagnosis query",
        )
    if any(w in q for w in ("improve", "position", "highlight", "convert", "listing", "bsr")):
        return Plan(
            query_type="improve",
            tool_sequence=["review_qa", "competitor_search"],
            rationale="Fallback plan for improve-type query",
        )
    return Plan(
        query_type="unknown",
        tool_sequence=["review_qa", "predict_return_risk"],
        rationale="Fallback plan — query type unclear, start with review evidence",
    )


def plan_node(state: AgentState) -> dict:
    """Classify the query and pick the initial tool sequence."""
    client = instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))
    product_name = state.get("product_name") or state["asin"]

    user_msg = (
        f"Seller's product: {product_name} (ASIN: {state['asin']}).\n"
        f"Seller's question: {state['query']}\n\n"
        f"Produce the Plan now."
    )

    try:
        plan: Plan = client.chat.completions.create(
            model=_model(),
            response_model=Plan,
            max_retries=2,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
    except Exception as e:
        print(f"[planner] structured call failed ({type(e).__name__}: {e}); using fallback")
        plan = _fallback_plan(state["query"])

    # Surface the plan into the message stream so it shows up in LangSmith
    # trace AND so the Executor's downstream prompts see it.
    plan_msg = AIMessage(
        content=(
            f"[Planner] query_type={plan.query_type}; "
            f"plan={list(plan.tool_sequence)}; "
            f"rationale={plan.rationale}"
        ),
        name="planner",
    )

    return {
        "query_type": plan.query_type,
        "plan": list(plan.tool_sequence),
        "tools_called": [],
        "iterations": 0,
        "replans_done": 0,
        "messages": [plan_msg],
    }
