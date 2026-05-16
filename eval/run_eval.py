"""Main eval runner for ListingLens Copilot.

Usage:
    # Full eval — 30 gold queries through the multi-node agent
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
"""
import argparse
import json
import os
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

from backend.agent.graph import run_agent  # noqa: E402
from eval.baselines import run_baseline  # noqa: E402
from eval.trajectory_eval import aggregate_trajectory, trajectory_metrics  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DEFAULT = REPO_ROOT / "eval" / "gold_set.jsonl"
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


def _load_gold(path: Path, limit: int | None = None) -> list[dict]:
    queries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    if limit:
        queries = queries[:limit]
    return queries


def _judge_label() -> str:
    provider = os.getenv("JUDGE_PROVIDER", "anthropic")
    if provider == "anthropic":
        return os.getenv("JUDGE_MODEL_ANTHROPIC", "claude-haiku-4-5-20251001") + " (Anthropic)"
    return os.getenv("JUDGE_MODEL_OPENAI", "gpt-4o-mini") + " (OpenAI)"


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
    decision_match = rec["decision"] == gold["expected_decision"]

    base.update({
        "actual_decision": rec["decision"],
        "actual_confidence": rec["confidence"],
        "actual_tools": actual_tools,
        "n_tool_calls": out["trace"]["n_tool_calls"],
        "trajectory": traj,
        "decision_match": decision_match,
        "recommendation_summary": rec["summary"][:300],
        "evidence_count": len(rec["evidence"]),
        "_full_output": out,  # kept for judges; stripped before JSONL write
    })
    return base


def _judge_all(per_query: list[dict], gold_by_id: dict) -> None:
    """Run LLM-as-judge on each per-query result that succeeded. Mutates in place."""
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


def _summarize(per_query: list[dict], variant: str, with_judges: bool) -> dict:
    """Compute aggregate metrics over the per-query list."""
    n = len(per_query)
    n_errors = sum(1 for q in per_query if q.get("error"))
    n_success = n - n_errors

    decisions_match = sum(1 for q in per_query if q.get("decision_match"))
    decision_accuracy = decisions_match / n if n else 0.0

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
        judge_aggs = aggregate_judge_scores(
            [q for q in per_query if not q.get("error") and "decision_correctness" in q]
        )

    return {
        "variant": variant,
        "n_queries": n,
        "n_success": n_success,
        "n_errors": n_errors,
        "error_rate": round(n_errors / n, 3) if n else 0.0,
        "decision_accuracy": round(decision_accuracy, 3),
        "trajectory": trajectory_aggs,
        "latency": latency_stats,
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

    lines = [
        f"# Eval Report — {date.today().isoformat()} — {variant}",
        "",
        f"- **Variant:** `{variant}`",
        f"- **Queries:** {summary['n_queries']} ({summary['n_success']} success, {summary['n_errors']} errors)",
        f"- **Agent model:** `{os.getenv('AGENT_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')}`",
        f"- **Judge model:** `{_judge_label()}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Decision accuracy | {summary['decision_accuracy']:.1%} |",
        f"| Trajectory F1 (avg) | {summary['trajectory']['avg_f1']:.3f} |",
        f"| Trajectory precision (avg) | {summary['trajectory']['avg_precision']:.3f} |",
        f"| Trajectory recall (avg) | {summary['trajectory']['avg_recall']:.3f} |",
        f"| First-tool match rate | {summary['trajectory']['ordering_match_rate']:.1%} |",
        f"| Latency p50 / p95 (s) | {summary['latency']['p50']:.1f} / {summary['latency']['p95']:.1f} |",
        f"| Error rate | {summary['error_rate']:.1%} |",
    ]
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
    print(f"  -> {len(gold)} queries")

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
        per_query.append(_per_query_result(g, out, err, latency))

    if with_judges:
        _judge_all(per_query, gold_by_id)

    summary = _summarize(per_query, variant, with_judges)

    date_str = date.today().isoformat()
    jsonl_path = REPORTS_DIR / f"{date_str}-{tag}.jsonl"
    md_path = REPORTS_DIR / f"{date_str}-{tag}.md"

    _write_jsonl(per_query, jsonl_path)
    _write_report(summary, per_query, md_path, variant)

    print()
    print("=" * 70)
    print(f"  EVAL DONE — variant={variant}")
    print("=" * 70)
    print(json.dumps(summary, indent=2))
    print()
    print(f"  Report:  {md_path.relative_to(REPO_ROOT)}")
    print(f"  Raw:     {jsonl_path.relative_to(REPO_ROOT)}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
