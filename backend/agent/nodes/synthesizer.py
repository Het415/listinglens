"""Synthesizer node — converts the trajectory into a structured Recommendation.

Reads the message history (the planner's bookkeeping, the executor's
reasoning, and the tool results) and produces a `Recommendation` matching the
Pydantic schema.

Why this node degrades instead of raising
-----------------------------------------
It used to be one unguarded instructor call, and it was the only node in the
graph without a fallback — `planner.py` degrades to `_fallback_plan`,
`executor.py` retries then emits a content-only message so the graph can carry
on. So a single malformed generation here destroyed an otherwise successful
run: every tool had returned, the executor had often already written a
complete analysis, and the user got a raw `400 tool_use_failed` instead.

Observed in production 2026-09-17 12:56 UTC. Groq's daily token budget was
99.5% spent, so `resilient_call` walked the agent chain past two rate-limited
models onto `qwen/qwen3.8-27b`, which answered with its native XML tool-call
syntax (`<tool_call><function=Recommendation><parameter=decision>ngo`) rather
than JSON arguments — note `ngo` is not even in the decision Literal. The
same-model retry fired, produced the same thing, and with no models left the
exception propagated to the chat UI. Four tool results and a finished
markdown comparison were thrown away with it.

Retrying harder does not fix that; `resilient_call` already tries up to six
times across three models. What was missing is that the evidence is still
sitting in `state["messages"]` and can be assembled without the LLM. So on
total failure this node now builds a `Recommendation` locally from the tool
results and flags `synthesis_degraded`, which the trace carries to the UI so
a degraded answer is never displayed as a normal one.
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.llm_config import groq_client, reasoning_effort, resilient_call, thought_text

from ..prompts import SYNTHESIZER_SYSTEM_PROMPT
from ..schemas import AgentState, Evidence, Recommendation


# How much of a single tool result the Synthesizer gets to see.
#
# Was 1500, which silently deleted most of the evidence on every `review_qa`
# call. Measured on B08XPWDSWW, serialized exactly as LangGraph's ToolNode
# passes it (`json.dumps`, field order preserved):
#
#     review_qa            2239   <- the only tool over the old cap
#     competitor_search    1197
#     price_history         949
#     trend_signal          439
#     predict_return_risk   252
#
# `ReviewQAOutput` is `{answer, sources, n_sources}` in that order, so `answer`
# (963 chars) serializes first and the 1500 cut landed 739 chars inside
# `sources` (1235 chars, 5 entries). Only 2 of the 5 retrieved review snippets
# even STARTED before the cut. The Synthesizer was therefore writing its
# recommendation from the RAG's prose summary plus two quotes, not from the
# five snippets retrieval had actually found.
#
# That is the mechanism behind `evidence_relevance` being the weakest judge
# dimension (0.545-0.548 across three runs) while completeness stayed at ~0.87:
# the summary survived, the citable quotes did not. The judge never once
# complained about ranking, which is why this is a truncation bug and not the
# retrieval-ranking problem it was mistaken for.
#
# 3000 covers the measured worst case with headroom. It is bounded: `sources`
# is 5 entries each already truncated to 200 chars upstream
# (`rag_chatbot.ask_question`), and the RAG prompt caps `answer` at ~150 words,
# so review_qa cannot grow far past ~2500. Cost is ~185 tokens per run, and
# only on the one tool that exceeds the old limit.
_TOOL_RESULT_CHARS = 3000


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
            thought = thought_text(m)
            if thought:
                lines.append(f"EXECUTOR thought: {thought}")
        elif isinstance(m, ToolMessage):
            content = str(m.content)
            if len(content) > _TOOL_RESULT_CHARS:
                content = content[:_TOOL_RESULT_CHARS] + " ...[truncated]"
            lines.append(f"TOOL RESULT [{m.name}]: {content}")
    return "\n\n".join(lines)


# Cap on a tool result reused as degraded evidence. Generous compared with the
# transcript's own 1500-char budget because there is no model to confuse here —
# this text goes straight to the UI, and over-trimming it is what makes a
# degraded answer feel empty.
_DEGRADED_SNIPPET_CHARS = 600


def _executor_analysis(messages: list) -> str:
    """The executor's last substantive prose, if it wrote any.

    Worth recovering: on the production failure the executor had already
    produced a full markdown comparison table answering the question. Only the
    final structured call failed, so this is a real answer, not a guess.
    """
    for m in reversed(messages):
        if not isinstance(m, AIMessage):
            continue
        if getattr(m, "name", None) in ("planner", "synthesizer"):
            continue
        thought = thought_text(m).strip()
        # Skip the executor's degraded hand-off message and bare tool turns.
        if len(thought) > 120 and "unable to issue a further tool call" not in thought:
            return thought
    return ""


def _degraded_recommendation(state: AgentState, err: Exception) -> Recommendation:
    """Assemble a Recommendation from tool results when the LLM could not.

    Honest by construction: `decision` is `needs_more_data` and `confidence` is
    0.0 because no model judgement was obtained — these are not a hedge, they
    are the absence of an answer. What IS real is the evidence, so it is
    carried through verbatim from the tool results, and `risks` states plainly
    that the synthesis step failed.
    """
    messages = state.get("messages", [])

    evidence = [
        Evidence(
            tool=m.name or "unknown",
            snippet=(
                str(m.content)[:_DEGRADED_SNIPPET_CHARS] + " ...[truncated]"
                if len(str(m.content)) > _DEGRADED_SNIPPET_CHARS
                else str(m.content)
            ),
            # Not a similarity score and not a model judgement. 0.5 is a
            # deliberate "unscored" marker — every tool that ran is included
            # rather than ranked, because ranking is what failed.
            relevance=0.5,
        )
        for m in messages
        if isinstance(m, ToolMessage)
    ]

    analysis = _executor_analysis(messages)
    tools = state.get("tools_called", []) or [e.tool for e in evidence]

    if analysis:
        summary = (
            "The final recommendation could not be generated, but the research "
            "completed. Here is the analysis the agent produced:\n\n" + analysis
        )
    elif evidence:
        summary = (
            "The final recommendation could not be generated. The research did "
            f"complete — {len(evidence)} tool result(s) are included as evidence "
            "below and can be read directly."
        )
    else:
        summary = (
            "The agent could not complete this question: the final synthesis "
            "step failed before any evidence was gathered."
        )

    return Recommendation(
        decision="needs_more_data",
        confidence=0.0,
        summary=summary,
        reasoning_steps=[f"Called {t}" for t in tools],
        evidence=evidence,
        risks=[
            "This is a degraded answer. The model returned output that did not "
            "match the required schema, so the decision and confidence above "
            f"are placeholders, not judgements ({type(err).__name__}).",
        ],
        suggested_next_actions=["Re-run the question — this failure is usually transient."],
        evidence_gaps=["A model-generated decision, confidence and risk assessment."],
    )


def synthesize_node(state: AgentState) -> dict:
    """Produce the Recommendation, degrading to local assembly on failure."""
    transcript = _build_transcript(
        messages=state.get("messages", []),
        query=state["query"],
        query_type=state.get("query_type", "unknown"),
        plan=state.get("plan", []),  # remaining plan items
    )

    degraded = False
    try:
        # Inside the try, so a client that cannot be built degrades like any
        # other synthesis failure instead of discarding the gathered evidence.
        client = groq_client()
        recommendation: Recommendation = resilient_call("agent", lambda model: client.chat.completions.create(
            model=model,
            response_model=Recommendation,
            max_retries=2,
            reasoning_effort=reasoning_effort("agent"),
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
        ))
    except Exception as e:  # noqa: BLE001 — provider exception types vary
        # Deliberately broad. `resilient_call` has already exhausted the model
        # chain, so whatever arrives here is terminal, and the whole point is
        # that no provider error should cost the user their completed research.
        print(
            f"[synthesizer] structured output failed after exhausting the model "
            f"chain ({type(e).__name__}: {str(e)[:200]}); "
            f"degrading to evidence assembled from tool results"
        )
        recommendation = _degraded_recommendation(state, e)
        degraded = True

    # Surface a short Synthesizer marker into messages so the trace is legible
    synth_msg = AIMessage(
        content=(
            f"[Synthesizer] {'DEGRADED — ' if degraded else ''}"
            f"decision={recommendation.decision}; "
            f"confidence={recommendation.confidence:.2f}"
        ),
        name="synthesizer",
    )

    return {
        "recommendation": recommendation,
        "messages": [synth_msg],
        "synthesis_degraded": degraded,
    }
