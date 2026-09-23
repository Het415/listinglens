"""A degraded agent run must not be scored as an answer.

The Synthesizer degrades instead of raising, so these rows reach the harness
with err=None and a placeholder decision. Left alone, that would award
decision-accuracy credit for runs where the model never decided anything, and
make error_rate look like it improved when failures were only reclassified.
"""

from __future__ import annotations

from eval.run_eval import _per_query_result, _summarize

GOLD_NMD = {
    "id": "launch_001", "query_type": "launch", "asin": "B08XPWDSWW",
    "query": "Should I launch a noise-cancelling variant?",
    "expected_decision": "needs_more_data",
    "expected_tools": ["competitor_search", "trend_signal"],
}
GOLD_GO = {**GOLD_NMD, "id": "returns_005", "expected_decision": "go"}


def _out(decision, *, degraded, tools=("competitor_search", "trend_signal")):
    return {
        "recommendation": {
            "decision": decision, "confidence": 0.0 if degraded else 0.85,
            "summary": "s", "evidence": [],
        },
        "trace": {
            "tools_called": list(tools), "n_tool_calls": len(tools),
            "iterations": 2, "synthesis_degraded": degraded,
        },
    }


def test_degraded_row_is_flagged():
    row = _per_query_result(GOLD_NMD, _out("needs_more_data", degraded=True), None, 30.0)
    assert row["synthesis_degraded"] is True


def test_degraded_row_never_counts_as_correct_even_when_it_matches_gold():
    """The regression guard: gold is needs_more_data and so is the placeholder."""
    row = _per_query_result(GOLD_NMD, _out("needs_more_data", degraded=True), None, 30.0)
    assert row["actual_decision"] == "needs_more_data"
    assert row["decision_match"] is False, "a placeholder must not earn credit"


def test_normal_row_still_scores_normally():
    row = _per_query_result(GOLD_NMD, _out("needs_more_data", degraded=False), None, 30.0)
    assert row["decision_match"] is True
    assert row["synthesis_degraded"] is False

    wrong = _per_query_result(GOLD_GO, _out("no_go", degraded=False), None, 30.0)
    assert wrong["decision_match"] is False


def test_missing_flag_is_treated_as_not_degraded():
    """Older traces predate the field; they must not all become degraded."""
    out = _out("go", degraded=False)
    del out["trace"]["synthesis_degraded"]
    row = _per_query_result(GOLD_GO, out, None, 12.0)
    assert row["synthesis_degraded"] is False
    assert row["decision_match"] is True


def test_summary_separates_degraded_from_success_and_errors():
    rows = [
        _per_query_result(GOLD_GO, _out("go", degraded=False), None, 10.0),
        _per_query_result(GOLD_NMD, _out("needs_more_data", degraded=True), None, 30.0),
        _per_query_result(GOLD_GO, None, RuntimeError("boom"), 5.0),
    ]
    s = _summarize(rows, variant="full", with_judges=False)

    assert s["n_queries"] == 3
    assert s["n_success"] == 1, "only the real recommendation counts as success"
    assert s["n_errors"] == 1
    assert s["n_degraded"] == 1


def test_no_decision_rate_is_the_comparable_headline():
    """error_rate alone would read as an improvement after the Synthesizer fix."""
    rows = [
        _per_query_result(GOLD_GO, _out("go", degraded=False), None, 10.0),
        _per_query_result(GOLD_NMD, _out("needs_more_data", degraded=True), None, 30.0),
    ]
    s = _summarize(rows, variant="full", with_judges=False)

    assert s["error_rate"] == 0.0, "nothing raised"
    assert s["no_decision_rate"] == 0.5, "but half the runs produced no decision"


# ── Executor degradation (audit E-12, CMD-06) ─────────────────────────────────
#
# The Executor tells the Synthesizer to "note the missing step as an evidence
# gap" when it gives up on a tool call, which forces needs_more_data. With no
# flag, CMD-06 showed that run scoring decision_match=True on a launch row.

def _executor_degraded_out(decision="needs_more_data"):
    out = _out(decision, degraded=False, tools=())
    out["trace"]["executor_degraded"] = True
    return out


def test_executor_degraded_row_never_counts_as_correct():
    """CMD-06 inverted: the forced hedge matches gold, and must still be False."""
    row = _per_query_result(GOLD_NMD, _executor_degraded_out(), None, 20.0)
    assert row["actual_decision"] == GOLD_NMD["expected_decision"]
    assert row["decision_match"] is False
    assert row["executor_degraded"] is True
    assert row["degraded"] is True


def test_executor_degraded_rows_count_as_no_decision():
    rows = [
        _per_query_result(GOLD_GO, _out("go", degraded=False), None, 10.0),
        _per_query_result(GOLD_NMD, _executor_degraded_out(), None, 20.0),
    ]
    s = _summarize(rows, variant="full", with_judges=False)
    assert s["n_degraded"] == 1
    assert s["no_decision_rate"] == 0.5


def test_a_flagless_row_still_scores_as_before():
    """The CMD-06 input without the new flag is an ordinary row."""
    row = _per_query_result(GOLD_NMD, _out("needs_more_data", degraded=False), None, 20.0)
    assert row["decision_match"] is True
    assert row["executor_degraded"] is False
