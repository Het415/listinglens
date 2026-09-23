"""Main eval runner for ListingLens Copilot.

Usage:
    # Full eval — every gold query through the multi-node agent
    python -m eval.run_eval

    # 5-query smoke eval (used by GitHub Actions on PRs)
    python -m eval.run_eval --limit 5

    # Baselines
    python -m eval.run_eval --baseline no_tool
    python -m eval.run_eval --baseline single_tool

    # Skip the LLM-as-judge step (saves $; useful when iterating on agent code)
    python -m eval.run_eval --no-judge --limit 3

The runner outputs:
  - eval/reports/YYYY-MM-DD-{variant}.md (summary report)
  - eval/reports/YYYY-MM-DD-{variant}.jsonl (per-query raw results)

Both are stamped with the git SHA (and whether tracked files were modified),
the sha256 of the gold set and of backend/agent/prompts.py, and the deepeval
version, so a number can be traced to exactly what produced it.

Exit status: 0 when every row produced a model decision; 2 when any row
errored or degraded (the eval gate, audit E-10); 1 for a configuration error
such as a missing judge key. `--limit N` runs a stratified smoke subset, not
the first N rows (see SMOKE_STRATA).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import date
from pathlib import Path
from statistics import median

from dotenv import load_dotenv

# override=True: the parent shell may have Claude Code's internal
# ANTHROPIC_API_KEY/ANTHROPIC_BASE_URL exported, which only work through
# Claude Code's auth proxy. The eval needs the user's own public-API key
# from .env to reach console.anthropic.com.
load_dotenv(override=True)
# Defensive: clear the Claude Code proxy base URL so the Anthropic SDK
# falls back to its default (api.anthropic.com) regardless of shell state.
os.environ.pop("ANTHROPIC_BASE_URL", None)

# Pin OpenMP to one thread before faiss / xgboost / sklearn load.
#
# Each of those wheels bundles its own OpenMP runtime (faiss/.dylibs/libomp.dylib,
# sklearn/.dylibs/libomp.dylib, plus xgboost's). Running FAISS similarity_search
# and then XGBoost in the same process segfaults on macOS — SIGSEGV, exit 139,
# no diagnostic message at all. It is fully deterministic: 3/3 crashes without
# this, 5/5 clean with it. The trigger in the eval was returns_001, the first
# gold query to call predict_return_risk after earlier queries had exercised
# review_qa; the whole run died at 11/30.
#
# Note KMP_DUPLICATE_LIB_OK=TRUE does NOT fix this (still 139) despite being the
# usual advice for duplicate-OpenMP problems. Limiting the thread count does.
# Single-threaded costs nothing here: IndexFlatL2 over a few thousand vectors is
# microseconds, and the XGBoost model is tiny.
os.environ.setdefault("OMP_NUM_THREADS", "1")

from backend.agent.graph import run_agent  # noqa: E402
from eval.baselines import run_baseline  # noqa: E402
from eval.trajectory_eval import aggregate_trajectory, trajectory_metrics  # noqa: E402
from src.llm_config import agent_model, executor_model, rag_model  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DEFAULT = REPO_ROOT / "eval" / "gold_set.jsonl"
REPORTS_DIR = REPO_ROOT / "eval" / "reports"

# Only `launch` queries have a decision that can be right or wrong.
#
# Measured on the 30-query gold set: expected_decision is nearly a function of
# query_type alone —
#
#     returns  -> go 9,  needs_more_data 1
#     improve  -> go 8,  needs_more_data 2
#     launch   -> needs_more_data 6, go 2, no_go 2
#
# so on the 30-row set as measured 2026-09-17 a constant "always go" predictor
# scored 63.3% and a best-constant-per-type lookup 76.7%, both ABOVE the
# agent's 60.0%. (Three no_go rows were added after that measurement, taking
# those floors to 57.6% and 69.7% — the figures here are the observation that
# motivated the split, not live values. Everything below derives its baselines
# from the rows loaded at runtime, so the code does not care.) An all-types
# decision accuracy was therefore reporting label skew, not reasoning: it can be
# beaten by a dictionary.
#
# The cause is a task/label mismatch, not a weak agent. go/no_go/needs_more_data
# is launch-decision vocabulary. "Should I launch a wireless version?" has a real
# yes/no/unsure. "Why are returns spiking?" has no proposal to approve, so `go`
# collapses into "the agent answered" — which is why `go` dominates those two
# types while launch is spread across all three decisions.
#
# The headline therefore scores this set only. Other types keep their
# decision_match and stay in the per-type table, marked informational: a swing
# there is still worth seeing, it just is not an accuracy claim. Widening this
# set means first fixing the labels for the types added.
DECISION_SCORED_TYPES = frozenset({"launch"})


def _is_image_negative(row: dict) -> bool:
    """An images_* row whose answer must NOT involve the image tool."""
    return row["id"].startswith("images_") and "image_audit" not in row["expected_tools"]


# Every smoke run must contain at least one row of each. The old smoke was
# `queries[:5]`: launch_001..005, all expected `needs_more_data`, so an agent
# that always hedged scored 100% and a constant predictor passed (audit E-10).
SMOKE_STRATA: tuple[tuple[str, object], ...] = (
    ("go", lambda r: r["expected_decision"] == "go"),
    ("no_go", lambda r: r["expected_decision"] == "no_go"),
    ("needs_more_data", lambda r: r["expected_decision"] == "needs_more_data"),
    ("returns", lambda r: r["query_type"] == "returns"),
    ("improve", lambda r: r["query_type"] == "improve"),
    ("image_negative", _is_image_negative),
)


def _stratified_sample(queries: list[dict], limit: int) -> list[dict]:
    """A deterministic `limit`-row subset that covers every SMOKE_STRATA entry.

    Greedy cover: repeatedly take the row (in gold order) meeting the most
    still-uncovered strata; then fill any remaining slots with one row per
    (query_type, expected_decision) pair not yet present, in gold order. The
    result is returned in gold order, so reports stay comparable run to run.
    With too small a limit the cover is truncated and a warning printed.
    """
    picked: list[int] = []
    uncovered = [name for name, _ in SMOKE_STRATA]
    tests = dict(SMOKE_STRATA)
    while uncovered and len(picked) < limit:
        best, best_hits = None, []
        for i, row in enumerate(queries):
            if i in picked:
                continue
            hits = [name for name in uncovered if tests[name](row)]
            if len(hits) > len(best_hits):
                best, best_hits = i, hits
        if best is None:
            break  # the gold set has no row for what is left
        picked.append(best)
        uncovered = [name for name in uncovered if name not in best_hits]
    if uncovered:
        print(f"  [smoke] warning: --limit {limit} does not cover {uncovered}")

    seen = {(queries[i]["query_type"], queries[i]["expected_decision"]) for i in picked}
    for i, row in enumerate(queries):
        if len(picked) >= limit:
            break
        key = (row["query_type"], row["expected_decision"])
        if i not in picked and key not in seen:
            picked.append(i)
            seen.add(key)
    for i in range(len(queries)):  # still short: plain gold order
        if len(picked) >= limit:
            break
        if i not in picked:
            picked.append(i)
    return [queries[i] for i in sorted(picked)]


def _load_gold(path: Path, limit: int | None = None) -> list[dict]:
    queries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    if limit:
        queries = _stratified_sample(queries, limit)
    return queries


PROMPTS_PATH = REPO_ROOT / "backend" / "agent" / "prompts.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _provenance(gold_path: Path) -> dict:
    """What produced this run, recorded on the report and on every row.

    The README's headline eval recorded none of this and could not be re-run
    at HEAD (audit E-13). `git_dirty` counts modified tracked files only, so
    local scratch files do not mark every run dirty.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        deepeval_version = version("deepeval")
    except PackageNotFoundError:
        deepeval_version = "not installed"
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {
        "git_sha": _git("rev-parse", "HEAD") or "unknown",
        "git_dirty": None if status is None else bool(status),
        "gold_sha256": _sha256(gold_path),
        "prompts_sha256": _sha256(PROMPTS_PATH),
        "deepeval": deepeval_version,
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:  # a --gold or reports dir outside the repo
        return str(path)


def _provenance_line(prov: dict) -> str:
    dirty = {True: " (dirty: modified tracked files)", False: "", None: " (dirty: unknown)"}
    return (
        f"- **Commit:** `{prov['git_sha']}`{dirty[prov['git_dirty']]} · "
        f"**gold** sha256 `{prov['gold_sha256'][:12]}` · "
        f"**prompts.py** sha256 `{prov['prompts_sha256'][:12]}` · "
        f"**deepeval** `{prov['deepeval']}`"
    )


def _judge_label() -> str:
    provider = os.getenv("JUDGE_PROVIDER", "anthropic")
    if provider == "anthropic":
        return os.getenv("JUDGE_MODEL_ANTHROPIC", "claude-haiku-4-5-20251001") + " (Anthropic)"
    return os.getenv("JUDGE_MODEL_OPENAI", "gpt-4o-mini") + " (OpenAI)"


def _judge_line(with_judges: bool) -> str:
    """Report header text for the judge row.

    Must distinguish "judged by X" from "not judged at all". The header used to
    print _judge_label() unconditionally, so a `--no-judge` run still claimed
    `Judge model: claude-haiku-4-5-20251001 (Anthropic)` — and since `variant`
    defaults to "full" whenever no baseline is selected, the report looked like
    a complete judged run. eval/reports/2026-09-15-postfix.md is exactly that:
    a --no-judge run whose header names a judge, with no judge scores in the
    accompanying .jsonl.
    """
    if not with_judges:
        return "_not run_ (`--no-judge`) — no LLM-as-judge scores in this report"
    return f"`{_judge_label()}`"


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _run_one(asin: str, query: str, variant: str) -> tuple[dict | None, Exception | None, float]:
    """Run one query through the chosen variant. Returns (agent_output_dict, error, latency)."""
    t0 = time.time()
    try:
        if variant == "full":
            out = run_agent(asin=asin, query=query)
        else:
            out = run_baseline(variant, asin=asin, query=query)
        return out.model_dump(), None, time.time() - t0
    except Exception as e:
        return None, e, time.time() - t0


def _per_query_result(gold: dict, out: dict | None, err: Exception | None, latency: float) -> dict:
    base = {
        "id": gold["id"],
        "query_type": gold["query_type"],
        "asin": gold["asin"],
        "query": gold["query"],
        "expected_decision": gold["expected_decision"],
        "expected_tools": gold["expected_tools"],
        "latency_s": round(latency, 2),
    }

    if err is not None:
        base.update({
            "error": f"{type(err).__name__}: {err}",
            "actual_decision": None,
            "actual_tools": [],
            "trajectory": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "ordering_match": False, "score": 0.0},
            "decision_match": False,
        })
        return base

    rec = out["recommendation"]
    actual_tools = out["trace"]["tools_called"]
    traj = trajectory_metrics(gold["expected_tools"], actual_tools)

    # A degraded run is NOT an answer, and must not be scored as one.
    #
    # The Synthesizer now assembles a Recommendation from tool results when its
    # structured output fails, instead of raising. That is right for users, but
    # it silently changes what this function sees: the row arrives with err=None
    # and decision="needs_more_data", so it would be counted as a genuine
    # decision — and scored CORRECT on every gold row that happens to expect
    # needs_more_data. That is unearned credit for a run where the model never
    # committed to anything, and it would also make error_rate look like it
    # improved when the failures were merely reclassified.
    #
    # So a degraded row is recorded explicitly, never matches, and is counted
    # separately in the summary.
    #
    # The same holds when the Executor gave up on a tool call. It tells the
    # Synthesizer to "note the missing step as an evidence gap", which forces
    # needs_more_data, so a budget-exhausted run used to be credited as a
    # correct hedge on every launch row expecting one (audit E-12, CMD-06).
    synthesis_degraded = bool(out["trace"].get("synthesis_degraded"))
    executor_degraded = bool(out["trace"].get("executor_degraded"))
    degraded = synthesis_degraded or executor_degraded
    decision_match = (not degraded) and rec["decision"] == gold["expected_decision"]

    base.update({
        "actual_decision": rec["decision"],
        "actual_confidence": rec["confidence"],
        "actual_tools": actual_tools,
        "n_tool_calls": out["trace"]["n_tool_calls"],
        "trajectory": traj,
        "decision_match": decision_match,
        "degraded": degraded,
        "synthesis_degraded": synthesis_degraded,
        "executor_degraded": executor_degraded,
        "recommendation_summary": rec["summary"][:300],
        "evidence_count": len(rec["evidence"]),
        "_full_output": out,  # kept for judges; stripped before JSONL write
    })
    return base


def _judge_all(
    per_query: list[dict], gold_by_id: dict, jsonl_path: Path | None = None
) -> None:
    """Run LLM-as-judge on each per-query result that succeeded. Mutates in place.

    `jsonl_path` makes the pass crash-safe: judging 30 queries is ~120 API calls,
    and a rate-limit wall or segfault partway through used to discard every score
    already paid for. Flushing after each query means a re-run can be reasoned
    about from what landed.
    """
    print(f"\n[judges] running 4-dimension LLM-as-judge on {len(per_query)} queries...")
    from eval.judges import judge_recommendation
    from backend.agent.schemas import AgentOutput

    for i, q in enumerate(per_query, 1):
        if q.get("error") or "_full_output" not in q:
            for k in ("decision_correctness", "evidence_relevance", "anti_hallucination", "completeness"):
                q[k] = {"score": None, "reason": "skipped (run errored)"}
            continue

        gold = gold_by_id[q["id"]]
        # Reconstruct AgentOutput for the judges
        out = AgentOutput.model_validate(q["_full_output"])
        scores = judge_recommendation(out, gold)
        q.update(scores)
        print(f"  [{i}/{len(per_query)}] {q['id']}: "
              f"dec={scores['decision_correctness']['score']} "
              f"ev={scores['evidence_relevance']['score']} "
              f"hal={scores['anti_hallucination']['score']} "
              f"comp={scores['completeness']['score']}")
        if jsonl_path is not None:
            _write_jsonl(per_query, jsonl_path)


def _majority_baseline(rows: list[dict]) -> tuple[str | None, int]:
    """Most common `expected_decision` among `rows`, and how many rows carry it.

    This is the score a constant predictor gets, i.e. the floor any accuracy
    figure over the same rows has to clear before it means anything. Ties break
    alphabetically so two runs over the same rows never name different labels.
    """
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["expected_decision"]] = counts.get(r["expected_decision"], 0) + 1
    if not counts:
        return None, 0
    label = min(counts, key=lambda d: (-counts[d], d))
    return label, counts[label]


def _decision_breakdown(per_query: list[dict]) -> dict:
    """Decision accuracy split by query_type, each figure paired with its baseline.

    Every number here is derived from the rows in *this* run. The gold set is
    still growing and its class balance shifts as `no_go` launch cases are added,
    so a hardcoded n, baseline or class distribution would quietly start lying —
    and a `--limit` run would report the full set's floor against a subset's
    accuracy. Deriving at runtime also makes the limit case self-describing.

    Degraded rows need no special handling: `_per_query_result` already pins
    their decision_match to False, so they cannot earn credit inside the
    per-type numbers either. They still count toward `n` and toward the
    baselines, which is correct — a baseline predictor would have answered them.
    """
    by_type: dict[str, list[dict]] = {}
    for q in per_query:
        by_type.setdefault(q["query_type"], []).append(q)

    per_type: dict[str, dict] = {}
    # Score of the strongest lookup table available: the best constant *within*
    # each query_type. On the 2026-09-17 set this was 76.7%, and it is the number
    # an all-types accuracy actually competes with.
    per_type_constant_correct = 0
    for qt in sorted(by_type):
        rows = by_type[qt]
        correct = sum(1 for r in rows if r.get("decision_match"))
        label, label_n = _majority_baseline(rows)
        per_type_constant_correct += label_n
        per_type[qt] = {
            "n": len(rows),
            "correct": correct,
            "accuracy": round(correct / len(rows), 3),
            "baseline_decision": label,
            "baseline_accuracy": round(label_n / len(rows), 3),
            "scored": qt in DECISION_SCORED_TYPES,
        }

    n = len(per_query)
    scored_rows = [q for q in per_query if q["query_type"] in DECISION_SCORED_TYPES]
    n_scored = len(scored_rows)
    scored_correct = sum(1 for q in scored_rows if q.get("decision_match"))
    scored_label, scored_label_n = _majority_baseline(scored_rows)

    all_correct = sum(1 for q in per_query if q.get("decision_match"))
    const_label, const_n = _majority_baseline(per_query)

    return {
        # The headline — scored types only. Paired with the floor it must beat,
        # because the two were never meant to be read apart.
        "decision_accuracy": round(scored_correct / n_scored, 3) if n_scored else 0.0,
        "decision_baseline": round(scored_label_n / n_scored, 3) if n_scored else 0.0,
        "decision_baseline_label": scored_label,
        # Published so "60%" can never be mistaken for "of all queries" — a
        # --limit run may have few scored rows, or none at all.
        "decision_scored_types": sorted(DECISION_SCORED_TYPES),
        "decision_scored_n": n_scored,
        "decision_scored_correct": scored_correct,
        # What the old headline measured. Kept for continuity with earlier
        # reports, renamed so nothing can read it as the scored figure.
        "decision_accuracy_all_types": round(all_correct / n, 3) if n else 0.0,
        "decision_baseline_all_types": round(const_n / n, 3) if n else 0.0,
        "decision_baseline_all_types_label": const_label,
        "decision_baseline_per_type": round(per_type_constant_correct / n, 3) if n else 0.0,
        "decision_by_type": per_type,
    }


def _row_degraded(q: dict) -> bool:
    # Rows written before `degraded` existed carry only synthesis_degraded.
    return bool(q.get("degraded") or q.get("synthesis_degraded") or q.get("executor_degraded"))


def _summarize(per_query: list[dict], variant: str, with_judges: bool) -> dict:
    """Compute aggregate metrics over the per-query list."""
    n = len(per_query)
    n_errors = sum(1 for q in per_query if q.get("error"))
    # Degraded runs completed without raising but produced no model decision.
    # Tracked apart from both buckets so a drop in error_rate cannot be read as
    # an improvement when it is really a reclassification. n_success counts only
    # runs that actually produced a model-generated recommendation.
    n_degraded = sum(1 for q in per_query if _row_degraded(q))
    n_success = n - n_errors - n_degraded

    decision = _decision_breakdown(per_query)

    trajectory_aggs = aggregate_trajectory(
        [q["trajectory"] for q in per_query if not q.get("error")]
    )

    latencies = [q["latency_s"] for q in per_query]
    latency_stats = {
        "avg": round(sum(latencies) / n, 2) if n else 0.0,
        "p50": round(median(latencies), 2) if latencies else 0.0,
        "p95": round(_percentile(latencies, 0.95), 2) if latencies else 0.0,
    }

    judge_aggs = {}
    if with_judges:
        from eval.judges import aggregate_judge_scores
        # Degraded rows are excluded alongside errored ones: their `summary`
        # is the executor's prose, not a synthesized recommendation, so judging
        # it would mix "how good is the agent's answer" with "how readable was
        # the fallback".
        judge_aggs = aggregate_judge_scores(
            [
                q for q in per_query
                if not q.get("error")
                and not _row_degraded(q)
                and "decision_correctness" in q
            ]
        )

    return {
        "variant": variant,
        "n_queries": n,
        "n_success": n_success,
        "n_errors": n_errors,
        "n_degraded": n_degraded,
        "error_rate": round(n_errors / n, 3) if n else 0.0,
        # The honest headline: any run that did not yield a model decision,
        # whether it raised or degraded. Compare THIS against historical
        # error_rate figures, not error_rate itself.
        "no_decision_rate": round((n_errors + n_degraded) / n, 3) if n else 0.0,
        # decision_accuracy (scored types only), decision_accuracy_all_types and
        # the baselines every one of them has to beat. See DECISION_SCORED_TYPES.
        **decision,
        "trajectory": trajectory_aggs,
        "latency": latency_stats,
        # Recorded so the report can say whether judging ran instead of
        # advertising a judge model unconditionally. A --no-judge run used to
        # print "Judge model: claude-haiku-4-5-..." in its header, which made
        # unjudged reports read as judged ones.
        "with_judges": with_judges,
        "judges": judge_aggs,
    }


def _write_jsonl(per_query: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for q in per_query:
            # Strip the heavy full_output before writing
            q_clean = {k: v for k, v in q.items() if k != "_full_output"}
            f.write(json.dumps(q_clean) + "\n")


def _write_report(summary: dict, per_query: list[dict], path: Path, variant: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    j = summary.get("judges", {})

    def _fmt(v):
        return "N/A" if v is None else f"{v:.3f}"

    # Every accuracy cell below carries its own baseline. A reader who sees only
    # "60.0%" has no way to know that a lookup table over query_type scores
    # a per-type lookup on the same rows; that omission made the old headline
    # misleading, so the two travel together from here on.
    scored_types = ", ".join(f"`{t}`" for t in summary.get("decision_scored_types", [])) or "(none)"
    n_scored = summary.get("decision_scored_n", 0)
    if n_scored:
        headline_cell = (
            f"**{summary['decision_accuracy']:.1%}** "
            f"(vs {summary.get('decision_baseline', 0.0):.1%} majority baseline — "
            f"always `{summary.get('decision_baseline_label')}`)"
        )
    else:
        headline_cell = "n/a — this run contained no scored rows"

    lines = [
        f"# Eval Report — {date.today().isoformat()} — {variant}",
        "",
        f"- **Variant:** `{variant}`",
        f"- **Queries:** {summary['n_queries']} ({summary['n_success']} success, "
        f"{summary['n_errors']} errors, {summary.get('n_degraded', 0)} degraded)",
        f"- **Agent model:** `{agent_model()}`",
        f"- **Executor model:** `{executor_model()}`",
        f"- **RAG model:** `{rag_model()}`",
        f"- **Judge:** {_judge_line(summary.get('with_judges', True))}",
        *([_provenance_line(summary["provenance"])] if summary.get("provenance") else []),
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Decision accuracy — scored types {scored_types}, n={n_scored} | {headline_cell} |",
        f"| Decision accuracy — all types (informational), n={summary['n_queries']} | "
        f"{summary.get('decision_accuracy_all_types', 0.0):.1%} "
        f"(vs {summary.get('decision_baseline_per_type', 0.0):.1%} per-type-constant baseline) |",
        f"| Trajectory F1 (avg) | {summary['trajectory']['avg_f1']:.3f} |",
        f"| Trajectory precision (avg) | {summary['trajectory']['avg_precision']:.3f} |",
        f"| Trajectory recall (avg) | {summary['trajectory']['avg_recall']:.3f} |",
        f"| First-tool match rate | {summary['trajectory']['ordering_match_rate']:.1%} |",
        f"| Latency p50 / p95 (s) | {summary['latency']['p50']:.1f} / {summary['latency']['p95']:.1f} |",
        f"| Error rate | {summary['error_rate']:.1%} |",
        f"| Degraded (no model decision) | {summary.get('n_degraded', 0)} |",
        # The figure to compare against historical error_rate values: before
        # the Synthesizer learned to degrade, every one of these raised.
        f"| No-decision rate | {summary.get('no_decision_rate', summary['error_rate']):.1%} |",
    ]

    by_type = summary.get("decision_by_type", {})
    if by_type:
        lines.extend([
            "",
            "### Decision accuracy by query type",
            "",
            f"Only {scored_types} counts toward the headline. `expected_decision` is "
            "launch-decision vocabulary; for the other types there is no proposal to "
            "approve, so `go` degenerates into \"the agent answered\" and the label is "
            "near-constant. Those rows are shown as _informational_ — a swing is worth "
            "seeing, but it is not an accuracy claim. Each baseline below is the best "
            "constant predictor **within that type**, computed from this run's rows.",
            "",
            "| Type | n | Correct | Accuracy | Majority baseline | Headline |",
            "|---|---|---|---|---|---|",
        ])
        for qt in sorted(by_type):
            t = by_type[qt]
            lines.append(
                f"| {qt} | {t['n']} | {t['correct']} | {t['accuracy']:.1%} "
                f"| `{t['baseline_decision']}` {t['baseline_accuracy']:.1%} "
                f"| {'**scored**' if t['scored'] else 'informational'} |"
            )
        lines.extend([
            "",
            f"Across all {summary['n_queries']} rows: a single constant "
            f"(`{summary.get('decision_baseline_all_types_label')}`) scores "
            f"{summary.get('decision_baseline_all_types', 0.0):.1%}, and the best constant "
            f"per query_type scores {summary.get('decision_baseline_per_type', 0.0):.1%}. "
            "An all-types accuracy at or below those is worse than a lookup table.",
        ])

    if j:
        lines.extend([
            "",
            "### LLM-as-judge",
            "",
            "| Dimension | Avg score |",
            "|---|---|",
            f"| Decision correctness | {_fmt(j.get('avg_decision_correctness'))} |",
            f"| Evidence relevance | {_fmt(j.get('avg_evidence_relevance'))} |",
            f"| Anti-hallucination (higher=better) | {_fmt(j.get('avg_anti_hallucination'))} |",
            f"| Completeness | {_fmt(j.get('avg_completeness'))} |",
        ])

    lines.extend([
        "",
        "## Per-query results",
        "",
        "| ID | Type | Expected | Actual | ✓ | Traj F1 | Tools called | Latency |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for q in per_query:
        check = "✓" if q.get("decision_match") else ("err" if q.get("error") else "✗")
        actual = q.get("actual_decision") or "ERROR"
        tools = ", ".join(q.get("actual_tools", [])) or "(none)"
        traj_f1 = q["trajectory"]["f1"] if not q.get("error") else 0.0
        lines.append(
            f"| {q['id']} | {q['query_type']} | {q['expected_decision']} | {actual} "
            f"| {check} | {traj_f1:.2f} | {tools} | {q['latency_s']:.1f}s |"
        )

    errored = [q for q in per_query if q.get("error")]
    if errored:
        lines.extend(["", "## Failure modes", ""])
        for q in errored:
            lines.append(f"- **{q['id']}**: {q['error']}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ListingLens Copilot eval")
    parser.add_argument("--gold", default=str(GOLD_DEFAULT))
    parser.add_argument("--limit", type=int, default=None, help="Only run first N queries (smoke eval)")
    parser.add_argument("--baseline", choices=["no_tool", "single_tool"], default=None,
                        help="Run a baseline instead of the full agent")
    parser.add_argument("--no-judge", action="store_true", help="Skip the LLM-as-judge step")
    parser.add_argument("--output-tag", default="", help="Suffix for the report filename")
    args = parser.parse_args()

    variant = args.baseline or "full"
    tag = args.output_tag or variant
    with_judges = not args.no_judge

    if with_judges:
        provider = os.getenv("JUDGE_PROVIDER", "anthropic")
        needed_key = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        if not os.getenv(needed_key):
            print(f"ERROR: {needed_key} not set in env (JUDGE_PROVIDER={provider}).")
            print(f"Either: (1) set {needed_key} in .env, "
                  f"(2) switch JUDGE_PROVIDER, or (3) re-run with --no-judge")
            return 1

    gold_path = Path(args.gold)
    print(f"Loading gold set: {gold_path}")
    gold = _load_gold(gold_path, limit=args.limit)
    gold_by_id = {g["id"]: g for g in gold}
    print(f"  -> {len(gold)} queries" + (f": {', '.join(g['id'] for g in gold)}" if args.limit else ""))
    provenance = _provenance(gold_path)
    print(f"  -> {_provenance_line(provenance)}")

    # Resolved before the loop so results can be flushed as they are produced.
    date_str = date.today().isoformat()
    jsonl_path = REPORTS_DIR / f"{date_str}-{tag}.jsonl"
    md_path = REPORTS_DIR / f"{date_str}-{tag}.md"

    print(f"\nRunning variant: {variant}")
    per_query: list[dict] = []
    for i, g in enumerate(gold, 1):
        t0 = time.time()
        print(f"  [{i}/{len(gold)}] {g['id']:>14}  {g['query'][:60]}...", end=" ", flush=True)
        out, err, latency = _run_one(g["asin"], g["query"], variant)
        if err:
            print(f"ERROR ({latency:.1f}s): {type(err).__name__}")
        else:
            actual = out["recommendation"]["decision"]
            match = "✓" if actual == g["expected_decision"] else "✗"
            n_tools = out["trace"]["n_tool_calls"]
            print(f"{actual} {match}  [{n_tools} tools, {latency:.1f}s]")
        row = _per_query_result(g, out, err, latency)
        row["provenance"] = provenance
        per_query.append(row)
        # Flush after every query. A full run is ~20 minutes of paid API calls;
        # previously a crash at gold query 11, returns_001 (see the OMP_NUM_THREADS note
        # above) left no artefact at all and threw away ten completed queries.
        _write_jsonl(per_query, jsonl_path)

    if with_judges:
        _judge_all(per_query, gold_by_id, jsonl_path)

    summary = _summarize(per_query, variant, with_judges)
    summary["provenance"] = provenance

    _write_jsonl(per_query, jsonl_path)
    _write_report(summary, per_query, md_path, variant)

    print()
    print("=" * 70)
    print(f"  EVAL DONE — variant={variant}")
    print("=" * 70)
    print(json.dumps(summary, indent=2))
    print()
    print(f"  Report:  {_display_path(md_path)}")
    print(f"  Raw:     {_display_path(jsonl_path)}")
    print()

    # The gate. Row errors used to become results and main() returned 0, so
    # the PR smoke was green with 5/5 NameErrors (audit E-10). Every row must
    # now yield a model decision: an error or a degraded run fails the job.
    failures = [
        f"{name}={summary[name]:.1%}"
        for name in ("error_rate", "no_decision_rate")
        if summary[name] > 0
    ]
    if failures:
        print(f"  EVAL GATE FAILED: {', '.join(failures)} — every row must produce a model decision")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
