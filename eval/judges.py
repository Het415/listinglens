"""LLM-as-judge metrics for the ListingLens Copilot eval harness.

Uses DeepEval's GEval primitive. Judge model defaults to Claude Haiku 4.5
(different family from the agent — Llama — so we avoid same-family bias).
Switch via JUDGE_PROVIDER env var: "anthropic" (default) or "openai".

Four dimensions:
  - decision_correctness: does agent's decision match the gold expected_decision?
  - evidence_relevance: do cited evidence snippets cover expected_evidence_themes?
  - hallucination: does the agent claim things the actual tool outputs don't support?
    (LOWER score = MORE hallucination, so this is treated as "anti-hallucination")
  - completeness: does the recommendation address all critical aspects of the question?

Each returns 0.0-1.0. DeepEval normalizes its native 0-5 scale.
"""
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.agent.schemas import AgentOutput

JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "anthropic")
JUDGE_MODEL_OPENAI = os.getenv("JUDGE_MODEL_OPENAI", "gpt-4o-mini")
# Default to Haiku 4.5 ($1/M in, $5/M out). The previous default
# (claude-3-haiku-20240307, the original Haiku 3 from March 2024) has been
# retired by Anthropic and now returns 404, silently zeroing out every judge
# score. Haiku 4.5 is also what eval/run_eval.py:_judge_label() advertises
# in the report header, so the two stay consistent.
# Override via JUDGE_MODEL_ANTHROPIC env var to use a cheaper or smarter judge.
JUDGE_MODEL_ANTHROPIC = os.getenv("JUDGE_MODEL_ANTHROPIC", "claude-haiku-4-5-20251001")


def _judge_model_instance():
    """Build the judge LLM (DeepEval-compatible) based on JUDGE_PROVIDER env var.

    Returns either a model identifier string (for OpenAI; DeepEval handles it
    natively) or a DeepEval model wrapper instance (for Anthropic).
    """
    if JUDGE_PROVIDER == "anthropic":
        from deepeval.models import AnthropicModel
        return AnthropicModel(model=JUDGE_MODEL_ANTHROPIC)
    if JUDGE_PROVIDER == "openai":
        return JUDGE_MODEL_OPENAI
    raise ValueError(
        f"Unknown JUDGE_PROVIDER={JUDGE_PROVIDER!r}. Use 'anthropic' or 'openai'."
    )


def _serialize_recommendation(out: "AgentOutput") -> str:
    """Render the AgentOutput in a stable, judge-friendly text form."""
    r = out.recommendation
    evidence_lines = "\n".join(
        f"  - [{e.tool}] (rel={e.relevance:.2f}) {e.snippet}" for e in r.evidence
    )
    return (
        f"Decision: {r.decision}\n"
        f"Confidence: {r.confidence:.2f}\n"
        f"Summary: {r.summary}\n"
        f"Reasoning steps:\n  " + "\n  ".join(f"- {s}" for s in r.reasoning_steps) + "\n"
        f"Evidence:\n{evidence_lines}\n"
        f"Risks:\n  " + "\n  ".join(f"- {x}" for x in r.risks) + "\n"
        f"Suggested next actions:\n  " + "\n  ".join(f"- {x}" for x in r.suggested_next_actions)
    )


def _gold_block(gold: dict) -> str:
    return (
        f"Expected decision: {gold['expected_decision']}\n"
        f"Expected tools: {gold['expected_tools']}\n"
        f"Expected evidence themes: {gold['expected_evidence_themes']}\n"
        f"Notes for the judge: {gold.get('notes', '')}"
    )


def _make_judges():
    """Build the 4 GEval metric instances. Imported lazily so the eval module
    can be loaded without deepeval installed if the user only wants to look
    at trajectory eval.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    decision_correctness = GEval(
        name="DecisionCorrectness",
        criteria=(
            "Determine whether the agent's `decision` field aligns with the "
            "gold expected_decision. The three valid decisions are 'go', "
            "'no_go', and 'needs_more_data'. Score 1.0 if they match exactly. "
            "Score 0.5 if the directional intent is similar (e.g., gold says "
            "'needs_more_data' and agent says 'go' but the agent's reasoning "
            "honestly acknowledges insufficient data). Score 0.0 if the agent "
            "made a confidently wrong call (e.g., gold says 'no_go' and agent "
            "says 'go' without acknowledging the disqualifying factor)."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        model=_judge_model_instance(),
        threshold=0.5,
        verbose_mode=False,
    )

    evidence_relevance = GEval(
        name="EvidenceRelevance",
        criteria=(
            "Determine whether the agent's `evidence` list covers the gold "
            "expected_evidence_themes. Each gold theme is a topic the agent's "
            "evidence should touch on (not literal text match — semantic). "
            "Score 1.0 if all themes are covered with concrete evidence. "
            "Score 0.5 if at least half are covered. Score 0.0 if the agent's "
            "evidence is generic or irrelevant to the question."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        model=_judge_model_instance(),
        threshold=0.5,
        verbose_mode=False,
    )

    hallucination = GEval(
        name="AntiHallucination",
        criteria=(
            "Determine whether the agent's claims are supported by the cited "
            "evidence. Score 1.0 (best) if every concrete claim in the summary "
            "and reasoning_steps maps to a specific evidence snippet. Score 0.5 "
            "if some claims are reasonable inferences from evidence but slightly "
            "overreach. Score 0.0 if the agent invents facts the evidence "
            "doesn't support, OR cites a tool but then claims something the "
            "tool's snippet didn't say. NOTE: higher score = LESS hallucination."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=_judge_model_instance(),
        threshold=0.5,
        verbose_mode=False,
    )

    completeness = GEval(
        name="Completeness",
        criteria=(
            "Determine whether the recommendation fully addresses the seller's "
            "question. A complete recommendation has: (1) a clear decision, "
            "(2) reasoning that connects evidence to decision, (3) concrete "
            "next actions, (4) acknowledged risks. Score 1.0 if all four are "
            "well-developed. Score 0.5 if 2-3 are present but shallow. "
            "Score 0.0 if the recommendation is vague or dodges the question."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=_judge_model_instance(),
        threshold=0.5,
        verbose_mode=False,
    )

    return {
        "decision_correctness": decision_correctness,
        "evidence_relevance": evidence_relevance,
        "anti_hallucination": hallucination,
        "completeness": completeness,
    }


def judge_recommendation(out: "AgentOutput", gold: dict) -> dict:
    """Run all 4 GEval judges on one AgentOutput vs the gold entry.

    Returns dict keyed by metric name with score + reason for each.
    """
    from deepeval.test_case import LLMTestCase

    judges = _make_judges()
    actual = _serialize_recommendation(out)
    gold_text = _gold_block(gold)

    test_case = LLMTestCase(
        input=gold["query"],
        actual_output=actual,
        expected_output=gold_text,
    )

    results: dict[str, dict] = {}
    for name, metric in judges.items():
        try:
            metric.measure(test_case)
            results[name] = {
                "score": round(float(metric.score), 3),
                "reason": str(metric.reason)[:400] if metric.reason else "",
            }
        except Exception as e:
            results[name] = {"score": None, "reason": f"judge error: {type(e).__name__}: {e}"}

    return results


def aggregate_judge_scores(per_query: list[dict]) -> dict:
    """Average each judge's score across queries (None scores skipped)."""
    if not per_query:
        return {}

    metric_names = ["decision_correctness", "evidence_relevance", "anti_hallucination", "completeness"]
    out: dict[str, float | None] = {}
    for name in metric_names:
        scores = [q[name]["score"] for q in per_query if q.get(name, {}).get("score") is not None]
        out[f"avg_{name}"] = round(sum(scores) / len(scores), 3) if scores else None
    return out
