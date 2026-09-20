"""Decision accuracy must never be reported without the baseline it has to beat.

On the measured 30-query gold set, `expected_decision` is nearly a function of
`query_type`, so a constant predictor scores 63.3% and a per-type lookup table
scores 76.7% — both above the agent's 60.0%. The headline therefore scores
`launch` only (the one type where go/no_go/needs_more_data is a real decision),
and every accuracy figure ships next to its own majority-class floor.

These tests run on synthetic rows: the real runner costs Groq tokens. The
distributions below are written out in full in each fixture, so the expected
numbers follow from the fixture and not from eval/gold_set.jsonl — which is
still growing, and whose class balance the runner must therefore read at
runtime rather than assume.
"""

from __future__ import annotations

import json

from eval.run_eval import (
    DECISION_SCORED_TYPES,
    _decision_breakdown,
    _per_query_result,
    _summarize,
    _write_report,
)


def _gold(qid: str, query_type: str, expected: str) -> dict:
    return {
        "id": qid, "query_type": query_type, "asin": "B08XPWDSWW",
        "query": "q", "expected_decision": expected,
        "expected_tools": ["competitor_search"],
    }


def _out(decision: str, *, degraded: bool = False) -> dict:
    return {
        "recommendation": {
            "decision": decision, "confidence": 0.0 if degraded else 0.85,
            "summary": "s", "evidence": [],
        },
        "trace": {
            "tools_called": ["competitor_search"], "n_tool_calls": 1,
            "iterations": 1, "synthesis_degraded": degraded,
        },
    }


def _row(qid, query_type, expected, actual, *, degraded=False, error=None):
    """One per-query result, built the way the runner builds it."""
    gold = _gold(qid, query_type, expected)
    if error is not None:
        return _per_query_result(gold, None, error, 1.0)
    return _per_query_result(gold, _out(actual, degraded=degraded), None, 1.0)


def _measured_shape(actual_by_type: dict[str, str]) -> list[dict]:
    """Rows reproducing the measured class balance of the 30-query gold set.

    returns -> go 9, needs_more_data 1
    improve -> go 8, needs_more_data 2
    launch  -> needs_more_data 6, go 2, no_go 2

    `actual_by_type` makes the agent answer with one fixed decision per type,
    which is what lets a test say exactly how many rows it got right.
    """
    spec = {
        "returns": ["go"] * 9 + ["needs_more_data"],
        "improve": ["go"] * 8 + ["needs_more_data"] * 2,
        "launch": ["needs_more_data"] * 6 + ["go"] * 2 + ["no_go"] * 2,
    }
    rows = []
    for qt, expectations in spec.items():
        for i, expected in enumerate(expectations):
            rows.append(_row(f"{qt}_{i:03d}", qt, expected, actual_by_type[qt]))
    return rows


# --- the motivating measurement -------------------------------------------

def test_baselines_expose_that_the_old_headline_was_beatable_by_a_lookup_table():
    always_go = _measured_shape({"returns": "go", "improve": "go", "launch": "go"})
    d = _decision_breakdown(always_go)

    # 19 of 30 golds are `go`, so the constant predictor and the "always go"
    # agent land on the same number — which is the point: that number was the
    # old headline.
    assert d["decision_baseline_all_types_label"] == "go"
    assert d["decision_baseline_all_types"] == 0.633
    assert d["decision_accuracy_all_types"] == 0.633
    # Best constant per type: go 9 + go 8 + needs_more_data 6 = 23/30.
    assert d["decision_baseline_per_type"] == 0.767


def test_per_type_baseline_is_the_within_type_majority_not_the_global_one():
    rows = _measured_shape({"returns": "go", "improve": "go", "launch": "go"})
    by_type = _decision_breakdown(rows)["decision_by_type"]

    assert by_type["returns"]["baseline_decision"] == "go"
    assert by_type["returns"]["baseline_accuracy"] == 0.9
    assert by_type["improve"]["baseline_decision"] == "go"
    assert by_type["improve"]["baseline_accuracy"] == 0.8
    # launch is the only type whose majority is not `go`
    assert by_type["launch"]["baseline_decision"] == "needs_more_data"
    assert by_type["launch"]["baseline_accuracy"] == 0.6


# --- headline scopes to launch --------------------------------------------

def test_headline_counts_only_scored_types():
    assert DECISION_SCORED_TYPES == frozenset({"launch"})

    rows = _measured_shape({
        "returns": "go",              # 9/10 right, contributes nothing
        "improve": "go",              # 8/10 right, contributes nothing
        "launch": "needs_more_data",  # 6/10 right — the whole headline
    })
    d = _decision_breakdown(rows)

    assert d["decision_scored_types"] == ["launch"]
    assert d["decision_scored_n"] == 10
    assert d["decision_scored_correct"] == 6
    assert d["decision_accuracy"] == 0.6
    assert d["decision_baseline"] == 0.6
    assert d["decision_baseline_label"] == "needs_more_data"
    # ...while the all-types figure, flattered by the skew, stays visible.
    assert d["decision_accuracy_all_types"] == 0.767


def test_unscored_rows_keep_decision_match_and_stay_in_the_table():
    rows = [
        _row("returns_000", "returns", "go", "go"),
        _row("returns_001", "returns", "go", "no_go"),
        _row("launch_000", "launch", "needs_more_data", "needs_more_data"),
    ]
    assert rows[0]["decision_match"] is True
    assert rows[1]["decision_match"] is False

    by_type = _decision_breakdown(rows)["decision_by_type"]
    assert by_type["returns"] == {
        "n": 2, "correct": 1, "accuracy": 0.5,
        "baseline_decision": "go", "baseline_accuracy": 1.0, "scored": False,
    }
    assert by_type["launch"]["scored"] is True


def test_scored_subset_size_is_published_so_the_headline_cannot_be_misread():
    rows = _measured_shape({"returns": "go", "improve": "go", "launch": "go"})
    s = _summarize(rows, variant="full", with_judges=False)

    assert s["n_queries"] == 30
    assert s["decision_scored_n"] == 10, "the headline denominator, stated outright"
    assert s["decision_scored_n"] < s["n_queries"]


# --- nothing about the gold set is hardcoded ------------------------------

def test_baselines_track_a_gold_set_that_grew_new_no_go_launch_cases():
    """The concurrent gold-set edit: more launch rows, different class balance.

    If any count, baseline or class distribution were frozen into the runner,
    this is where it would show up as a stale number.
    """
    base = _measured_shape({"returns": "go", "improve": "go", "launch": "go"})
    grown = base + [
        _row(f"launch_1{i:02d}", "launch", "no_go", "go") for i in range(8)
    ]

    d = _decision_breakdown(grown)
    launch = d["decision_by_type"]["launch"]
    assert launch["n"] == 18
    # no_go is now 10 of 18 launch rows, overtaking needs_more_data's 6.
    assert launch["baseline_decision"] == "no_go"
    assert launch["baseline_accuracy"] == round(10 / 18, 3)
    assert d["decision_scored_n"] == 18
    assert d["decision_accuracy"] == round(2 / 18, 3), "only the 2 base `go` launches hit"
    assert d["decision_accuracy_all_types"] == round(19 / 38, 3)


def test_majority_tie_breaks_deterministically():
    rows = [
        _row("launch_000", "launch", "go", "go"),
        _row("launch_001", "launch", "no_go", "go"),
    ]
    first = _decision_breakdown(rows)["decision_baseline_label"]
    second = _decision_breakdown(list(reversed(rows)))["decision_baseline_label"]
    assert first == second == "go", "alphabetical tie-break, stable across row order"


# --- degraded rows stay uncredited everywhere -----------------------------

def test_degraded_launch_row_is_not_correct_in_the_per_type_numbers():
    """Same guard as the headline one, now inside the per-type breakdown.

    A degraded row's placeholder is `needs_more_data`, which is the launch
    majority — precisely the label it would be rewarded for most often.
    """
    rows = [
        _row("launch_000", "launch", "needs_more_data", "needs_more_data", degraded=True),
        _row("launch_001", "launch", "needs_more_data", "needs_more_data"),
    ]
    s = _summarize(rows, variant="full", with_judges=False)

    assert s["n_degraded"] == 1
    assert s["decision_scored_correct"] == 1
    assert s["decision_accuracy"] == 0.5
    assert s["decision_by_type"]["launch"]["correct"] == 1
    # The degraded row still counts in n and in the baseline: a constant
    # predictor would have answered it, so excluding it would inflate the agent.
    assert s["decision_by_type"]["launch"]["n"] == 2
    assert s["decision_by_type"]["launch"]["baseline_accuracy"] == 1.0


# --- edges ----------------------------------------------------------------

def test_run_with_no_launch_rows_reports_zero_scored_rows():
    rows = [
        _row("returns_000", "returns", "go", "go"),
        _row("improve_000", "improve", "go", "go"),
    ]
    s = _summarize(rows, variant="full", with_judges=False)

    assert s["decision_scored_n"] == 0
    assert s["decision_accuracy"] == 0.0
    assert s["decision_baseline"] == 0.0
    assert s["decision_baseline_label"] is None
    assert s["decision_accuracy_all_types"] == 1.0, "the informational figure still works"
    assert "launch" not in s["decision_by_type"], "a type with zero rows is absent"


def test_limit_run_of_only_launch_rows():
    rows = [
        _row("launch_000", "launch", "needs_more_data", "needs_more_data"),
        _row("launch_001", "launch", "go", "no_go"),
        _row("launch_002", "launch", "no_go", "no_go"),
    ]
    s = _summarize(rows, variant="full", with_judges=False)

    assert s["decision_scored_n"] == s["n_queries"] == 3
    assert s["decision_accuracy"] == s["decision_accuracy_all_types"] == round(2 / 3, 3)
    # Three distinct labels, one each: alphabetical tie-break, 1/3 floor.
    assert s["decision_baseline"] == round(1 / 3, 3)
    assert s["decision_baseline_per_type"] == round(1 / 3, 3)


def test_run_where_every_row_errored():
    rows = [
        _row("launch_000", "launch", "needs_more_data", None, error=RuntimeError("boom")),
        _row("returns_000", "returns", "go", None, error=RuntimeError("boom")),
    ]
    s = _summarize(rows, variant="full", with_judges=False)

    assert s["n_errors"] == 2
    assert s["decision_accuracy"] == 0.0
    assert s["decision_accuracy_all_types"] == 0.0
    # Baselines come from the gold labels, which survive an errored run — so the
    # report still states how far below a constant predictor the run landed.
    assert s["decision_baseline"] == 1.0
    assert s["decision_by_type"]["returns"]["baseline_decision"] == "go"


def test_empty_run_does_not_divide_by_zero():
    d = _decision_breakdown([])
    assert d["decision_accuracy"] == 0.0
    assert d["decision_scored_n"] == 0
    assert d["decision_baseline_all_types_label"] is None
    assert d["decision_by_type"] == {}


# --- report + JSON --------------------------------------------------------

def test_summary_is_json_serializable():
    """DECISION_SCORED_TYPES is a frozenset; it must not leak into the summary."""
    rows = _measured_shape({"returns": "go", "improve": "go", "launch": "go"})
    s = _summarize(rows, variant="full", with_judges=False)
    assert json.loads(json.dumps(s))["decision_scored_types"] == ["launch"]


def test_report_shows_every_accuracy_next_to_its_baseline(tmp_path):
    rows = _measured_shape({"returns": "go", "improve": "go", "launch": "needs_more_data"})
    s = _summarize(rows, variant="full", with_judges=False)
    path = tmp_path / "report.md"
    _write_report(s, rows, path, "full")
    md = path.read_text()

    assert "Decision accuracy by query type" in md
    assert "n=10" in md, "the scored denominator is on the page"
    assert "60.0%" in md and "majority baseline" in md
    assert "informational" in md, "unscored types are labelled as such"
    assert "**scored**" in md
    # The comparison that makes the headline readable at all.
    assert "76.7%" in md and "per query_type" in md


def test_report_handles_a_run_with_no_scored_rows(tmp_path):
    rows = [_row("returns_000", "returns", "go", "go")]
    s = _summarize(rows, variant="full", with_judges=False)
    path = tmp_path / "report.md"
    _write_report(s, rows, path, "full")
    md = path.read_text()

    assert "no scored rows" in md, "better than printing 0.0% as if it were measured"
