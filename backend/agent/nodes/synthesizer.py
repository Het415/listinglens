"""Synthesizer node — converts the trajectory into a structured Recommendation.

Single instructor + Groq call. Reads the message history (which contains
the planner's bookkeeping, the executor's reasoning, and the tool results)
and produces a `Recommendation` matching the Pydantic schema.
"""
import os

import instructor
from groq import Groq
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..prompts import SYNTHESIZER_SYSTEM_PROMPT
from ..schemas import AgentState, Recommendation


def _model() -> str:
    return os.getenv("AGENT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


def _build_transcript(messages: list, query: str, query_type: str, plan: list[str]) -> str:
    """Compact, structured transcript of the agent's research."""
    lines = [
        f"USER QUESTION: {query}",
        f"PLANNER classified as: {query_type}",
        f"PLANNER initial plan: {plan}",
        "",
    ]
    for m in messages:
        if isinstance(m, SystemMessage):
            continue
        if isinstance(m, HumanMessage):
            continue  # already captured above as USER QUESTION
        if isinstance(m, AIMessage):
            if getattr(m, "name", None) == "planner":
                continue  # planner bookkeeping already captured
            if m.tool_calls:
                for tc in m.tool_calls:
                    lines.append(f"EXECUTOR called: {tc['name']}({tc.get('args', {})})")
            if m.content:
                lines.append(f"EXECUTOR thought: {m.content}")
        elif isinstance(m, ToolMessage):
            content = str(m.content)
            if len(content) > 1500:
                content = content[:1500] + " ...[truncated]"
            lines.append(f"TOOL RESULT [{m.name}]: {content}")
    return "\n\n".join(lines)


def synthesize_node(state: AgentState) -> dict:
    """Run instructor + Groq once to produce the Recommendation."""
    client = instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))

    transcript = _build_transcript(
        messages=state.get("messages", []),
        query=state["query"],
        query_type=state.get("query_type", "unknown"),
        plan=state.get("plan", []),  # remaining plan items
    )

    recommendation: Recommendation = client.chat.completions.create(
        model=_model(),
        response_model=Recommendation,
        max_retries=2,
        messages=[
            {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"--- Agent trajectory ---\n{transcript}\n\n"
                    f"--- End trajectory ---\n\n"
                    f"Produce the structured Recommendation now."
                ),
            },
        ],
    )

    # Surface a short Synthesizer marker into messages so the trace is legible
    synth_msg = AIMessage(
        content=(
            f"[Synthesizer] decision={recommendation.decision}; "
            f"confidence={recommendation.confidence:.2f}"
        ),
        name="synthesizer",
    )

    return {
        "recommendation": recommendation,
        "messages": [synth_msg],
    }
