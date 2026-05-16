"""Trajectory evaluation — F1 over expected vs actual tool sets + ordering bonus.

Pure Python, deterministic. Doesn't call any LLM. Trajectory is often more
diagnostic than the final answer: if the agent called the wrong tools,
the answer is wrong by accident even when it sounds plausible.
"""
from typing import Sequence


def trajectory_metrics(
    expected_tools: Sequence[str],
    actual_tools: Sequence[str],
    ordering_bonus: float = 0.1,
) -> dict:
    """Compute precision, recall, F1, and ordering bonus over tool sets.

    Args:
        expected_tools: gold-set tools (order matters only for the ordering bonus)
        actual_tools: tools the agent actually called (in call order, may include duplicates)
        ordering_bonus: bonus added to F1 if the first actual tool matches the first expected

    Returns:
        dict with precision, recall, f1, ordering_match (bool), score (f1 + bonus if matched)
    """
    expected_set = set(expected_tools)
    actual_set = set(actual_tools)

    if not actual_set and not expected_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "ordering_match": True, "score": 1.0}

    intersection = expected_set & actual_set
    precision = len(intersection) / len(actual_set) if actual_set else 0.0
    recall = len(intersection) / len(expected_set) if expected_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Ordering: did the agent pick the right tool first?
    ordering_match = bool(
        expected_tools and actual_tools and expected_tools[0] == actual_tools[0]
    )
    score = min(1.0, f1 + (ordering_bonus if ordering_match else 0.0))

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "ordering_match": ordering_match,
        "score": round(score, 3),
    }


def aggregate_trajectory(per_query: list[dict]) -> dict:
    """Aggregate per-query trajectory metrics into avgs for the summary report."""
    if not per_query:
        return {"avg_precision": 0.0, "avg_recall": 0.0, "avg_f1": 0.0, "ordering_match_rate": 0.0}

    n = len(per_query)
    return {
        "avg_precision": round(sum(q["precision"] for q in per_query) / n, 3),
        "avg_recall": round(sum(q["recall"] for q in per_query) / n, 3),
        "avg_f1": round(sum(q["f1"] for q in per_query) / n, 3),
        "ordering_match_rate": round(sum(1 for q in per_query if q["ordering_match"]) / n, 3),
        "avg_score": round(sum(q["score"] for q in per_query) / n, 3),
    }
