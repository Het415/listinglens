"""The eval must be able to fail, and its smoke subset must be able to catch
something (audit E-10, E-13).

Before: row errors became results and main() returned 0, so the PR smoke was
green with 5/5 NameErrors; and `--limit 5` meant launch_001..005, all expected
`needs_more_data`, so an always-hedging agent scored 100%.
"""

from __future__ import annotations

import json

import pytest

import eval.run_eval as run_eval

GOLD = run_eval.GOLD_DEFAULT


def _gold() -> list[dict]:
    return [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]


# ── stratified smoke ──────────────────────────────────────────────────────────

def test_smoke_subset_covers_every_stratum():
    rows = run_eval._load_gold(GOLD, limit=5)
    assert len(rows) == 5
    for name, test in run_eval.SMOKE_STRATA:
        assert any(test(r) for r in rows), f"smoke subset has no {name} row"


def test_smoke_subset_is_not_the_first_five_rows():
    assert [r["id"] for r in run_eval._load_gold(GOLD, limit=5)] != [r["id"] for r in _gold()[:5]]


def test_smoke_subset_is_deterministic_and_in_gold_order():
    a = run_eval._load_gold(GOLD, limit=5)
    assert a == run_eval._load_gold(GOLD, limit=5)
    order = [r["id"] for r in _gold()]
    assert [order.index(r["id"]) for r in a] == sorted(order.index(r["id"]) for r in a)


def test_a_constant_hedger_can_no_longer_pass_the_smoke():
    rows = run_eval._load_gold(GOLD, limit=5)
    assert any(r["expected_decision"] != "needs_more_data" for r in rows)


def test_no_limit_means_every_row():
    assert len(run_eval._load_gold(GOLD)) == len(_gold())


# ── exit status ───────────────────────────────────────────────────────────────

def _good_output(gold: dict) -> dict:
    return {
        "asin": gold["asin"], "query": gold["query"],
        "recommendation": {
            "decision": gold["expected_decision"], "confidence": 0.8, "summary": "s",
            "reasoning_steps": [], "evidence": [], "risks": [],
            "suggested_next_actions": [], "evidence_gaps": [],
        },
        "trace": {"tools_called": gold["expected_tools"], "n_tool_calls": 1,
                  "iterations": 1, "synthesis_degraded": False, "executor_degraded": False},
    }


@pytest.fixture
def offline_main(monkeypatch, tmp_path):
    """main() with the agent replaced by `behaviour(gold) -> (out, err)`."""
    monkeypatch.setattr(run_eval, "REPORTS_DIR", tmp_path)
    # main() refuses to start without a key; the agent is replaced, so this
    # one is never sent. CI has no .env, so it must be set here, not inherited.
    monkeypatch.setenv("GROQ_API_KEY", "gsk_dummy_never_sent")

    def run(behaviour, limit=5):
        by_query = {g["query"]: g for g in _gold()}

        def fake_run_one(asin, query, variant):
            out, err = behaviour(by_query[query])
            return out, err, 0.01

        monkeypatch.setattr(run_eval, "_run_one", fake_run_one)
        monkeypatch.setattr("sys.argv", ["run_eval", "--limit", str(limit), "--no-judge"])
        code = run_eval.main()
        jsonl = next(tmp_path.glob("*.jsonl"))
        md = next(tmp_path.glob("*.md"))
        return code, [json.loads(l) for l in jsonl.read_text().splitlines()], md.read_text()

    return run


def test_clean_run_exits_zero(offline_main):
    code, _, _ = offline_main(lambda g: (_good_output(g), None))
    assert code == 0


def test_any_row_error_fails_the_gate(offline_main):
    """The build-ci smoke: 5/5 NameError, exit 0. Now non-zero."""
    code, rows, _ = offline_main(lambda g: (None, NameError("name 'image_urls' is not defined")))
    assert code == 2
    assert all(r["error"] for r in rows)


def test_one_degraded_row_fails_the_gate(offline_main):
    def behaviour(g):
        out = _good_output(g)
        if g["expected_decision"] == "needs_more_data":
            out["trace"]["executor_degraded"] = True
        return out, None

    code, _, _ = offline_main(behaviour)
    assert code == 2


# ── provenance (minimal T-12) ─────────────────────────────────────────────────

def test_report_and_every_row_carry_provenance(offline_main):
    _, rows, md = offline_main(lambda g: (_good_output(g), None))
    prov = rows[0]["provenance"]
    assert set(prov) == {"git_sha", "git_dirty", "gold_sha256", "prompts_sha256", "deepeval"}
    assert all(r["provenance"] == prov for r in rows)
    assert prov["gold_sha256"] == run_eval._sha256(GOLD)
    assert prov["prompts_sha256"] == run_eval._sha256(run_eval.PROMPTS_PATH)
    assert len(prov["git_sha"]) == 40 and prov["git_dirty"] in (True, False)
    assert f"`{prov['git_sha']}`" in md
    assert prov["gold_sha256"][:12] in md and prov["prompts_sha256"][:12] in md


# ── no gold row inside the prompts (audit E-14) ───────────────────────────────

def test_no_gold_query_appears_in_the_prompts():
    """Three synthesizer few-shots were gold rows launch_001/006/010 verbatim,
    answers included: test-set leakage in every run since 2026-05-25."""
    prompts = run_eval.PROMPTS_PATH.read_text().lower()
    leaked = [g["id"] for g in _gold() if g["query"].lower() in prompts]
    assert leaked == [], f"gold queries found in prompts.py: {leaked}"


def test_no_gold_product_is_used_as_a_worked_example():
    """The few-shot section must not anchor on catalog products either."""
    prompts = run_eval.PROMPTS_PATH.read_text()
    examples = prompts[prompts.index("# Worked examples"):]
    for name in {g["product_name"] for g in _gold()}:
        assert name.lower() not in examples.lower(), name


@pytest.mark.parametrize("value", ["", None], ids=["empty", "unset"])
def test_a_missing_groq_key_is_a_config_error_not_degraded_rows(monkeypatch, capsys, value):
    """PR #9's smoke eval ran on a repo with no GROQ_API_KEY secret: five rows
    degraded, and the gate reported "no decision" instead of the cause."""
    if value is None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GROQ_API_KEY", value)
    monkeypatch.setattr(run_eval, "_run_one", lambda *a: pytest.fail("no row may run without a key"))
    monkeypatch.setattr("sys.argv", ["run_eval", "--limit", "5", "--no-judge"])

    assert run_eval.main() == 1
    out = capsys.readouterr().out
    assert "GROQ_API_KEY is not set" in out and "Actions secret" in out
