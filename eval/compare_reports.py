"""Diff two eval JSONL reports — answers "did my last change help or hurt?"

The eval harness writes per-query results to `eval/reports/YYYY-MM-DD-*.jsonl`.
After landing a prompt or schema change, run the eval again and feed both
files to this script. It prints:

  - Overall decision-accuracy delta
  - Per-query-type breakdown (launch / returns / improve / unknown)
  - Per-query flips (queries that newly pass + queries that newly fail)
  - Trajectory F1 delta if both files carry trajectory metrics
  - Judge-score deltas (decision_correctness, evidence_relevance, etc.)
    if both files were run with --judges

Usage:
  python -m eval.compare_reports                          # auto-picks latest 2
  python -m eval.compare_reports BEFORE.jsonl AFTER.jsonl # explicit
  python -m eval.compare_reports --markdown               # markdown table output

The script is read-only — it never touches the report files themselves.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


def _load(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _auto_pick_latest_two() -> tuple[Path, Path]:
    """Return (before, after) — the two most recently-modified .jsonl reports.

    Skips files that smell like baselines (no_tool / single_tool variants) so
    a before/after comparison defaults to the full-agent runs the user cares
    about. Override with explicit args when comparing baselines.
    """
    jsonls = sorted(
        (p for p in REPORTS_DIR.glob("*.jsonl") if "baseline" not in p.name),
        key=lambda p: p.stat().st_mtime,
    )
    if len(jsonls) < 2:
        sys.exit(
            f"need at least 2 .jsonl reports in {REPORTS_DIR} to auto-compare; "
            f"found {len(jsonls)}. Pass paths explicitly."
        )
    return jsonls[-2], jsonls[-1]


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows}


def _pct(num: int, denom: int) -> str:
    return f"{(num / denom * 100):.1f}%" if denom else "—"


def _signed(n: float, fmt: str = ".1f") -> str:
    """Render a delta with explicit sign — useful in tables.

    Strips any leading '+' from the caller's format spec to avoid double-plus
    output, then adds exactly one '+' for positive values.
    """
    fmt = fmt.lstrip("+")
    if n > 0:
        return f"+{n:{fmt}}"
    return f"{n:{fmt}}"


def _decision_accuracy(rows: list[dict]) -> tuple[int, int]:
    matches = sum(1 for r in rows if r.get("decision_match"))
    return matches, len(rows)


def _per_type_accuracy(rows: list[dict]) -> dict[str, tuple[int, int]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[r.get("query_type", "unknown")].append(r)
    return {qt: _decision_accuracy(rs) for qt, rs in buckets.items()}


def _avg_trajectory_f1(rows: list[dict]) -> float | None:
    f1s = [
        r["trajectory"]["f1"]
        for r in rows
        if isinstance(r.get("trajectory"), dict) and "f1" in r["trajectory"]
    ]
    return sum(f1s) / len(f1s) if f1s else None


def _avg_judge(rows: list[dict], key: str) -> float | None:
    scores = []
    for r in rows:
        v = r.get(key)
        if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
            scores.append(v["score"])
    return sum(scores) / len(scores) if scores else None


def _format_flip_rows(flips: list[tuple[dict, dict]]) -> list[str]:
    """Format flipped queries as one-line summaries."""
    out = []
    for before, after in flips:
        arrow = f"{before.get('actual_decision') or 'ERR'} → {after.get('actual_decision') or 'ERR'}"
        out.append(
            f"  {after['id']:<14} ({after['query_type']:<8}) "
            f"expected={after['expected_decision']:<16} {arrow}"
        )
    return out


def compare(before_path: Path, after_path: Path, as_markdown: bool) -> None:
    before = _load(before_path)
    after = _load(after_path)

    if not before or not after:
        sys.exit("one of the reports is empty")

    before_by_id = _by_id(before)
    after_by_id = _by_id(after)
    common_ids = sorted(set(before_by_id) & set(after_by_id))
    only_after = sorted(set(after_by_id) - set(before_by_id))
    only_before = sorted(set(before_by_id) - set(after_by_id))

    # Restrict comparison to overlapping queries so accuracy deltas are honest.
    before = [before_by_id[i] for i in common_ids]
    after = [after_by_id[i] for i in common_ids]

    # ── overall decision accuracy ────────────────────────────────────────────
    b_match, b_total = _decision_accuracy(before)
    a_match, a_total = _decision_accuracy(after)
    delta_pts = (a_match / a_total - b_match / b_total) * 100 if a_total else 0.0

    # ── per-query-type breakdown ─────────────────────────────────────────────
    b_per_type = _per_type_accuracy(before)
    a_per_type = _per_type_accuracy(after)
    all_types = sorted(set(b_per_type) | set(a_per_type))

    # ── flips ────────────────────────────────────────────────────────────────
    improvements: list[tuple[dict, dict]] = []
    regressions: list[tuple[dict, dict]] = []
    for qid in common_ids:
        b, a = before_by_id[qid], after_by_id[qid]
        if not b.get("decision_match") and a.get("decision_match"):
            improvements.append((b, a))
        elif b.get("decision_match") and not a.get("decision_match"):
            regressions.append((b, a))

    # ── trajectory + judges ──────────────────────────────────────────────────
    b_traj = _avg_trajectory_f1(before)
    a_traj = _avg_trajectory_f1(after)
    judge_keys = ("decision_correctness", "evidence_relevance",
                  "anti_hallucination", "completeness")
    judge_deltas: dict[str, tuple[float | None, float | None]] = {
        k: (_avg_judge(before, k), _avg_judge(after, k)) for k in judge_keys
    }

    # ── output ───────────────────────────────────────────────────────────────
    if as_markdown:
        _print_markdown(
            before_path, after_path,
            b_match, b_total, a_match, a_total, delta_pts,
            all_types, b_per_type, a_per_type,
            b_traj, a_traj, judge_deltas,
            improvements, regressions, only_before, only_after,
        )
    else:
        _print_plain(
            before_path, after_path,
            b_match, b_total, a_match, a_total, delta_pts,
            all_types, b_per_type, a_per_type,
            b_traj, a_traj, judge_deltas,
            improvements, regressions, only_before, only_after,
        )


def _print_plain(before_path, after_path, b_match, b_total, a_match, a_total,
                 delta_pts, all_types, b_per_type, a_per_type,
                 b_traj, a_traj, judge_deltas,
                 improvements, regressions, only_before, only_after):
    print(f"BEFORE  {before_path.name}  ({b_total} queries)")
    print(f"AFTER   {after_path.name}  ({a_total} queries)")
    print()
    print(f"Decision accuracy: {b_match}/{b_total} ({_pct(b_match, b_total)}) "
          f"→ {a_match}/{a_total} ({_pct(a_match, a_total)})  "
          f"[{_signed(delta_pts)} pts]")
    print()
    print("Per query type:")
    for qt in all_types:
        bm, bt = b_per_type.get(qt, (0, 0))
        am, at = a_per_type.get(qt, (0, 0))
        b_pct = bm / bt * 100 if bt else 0
        a_pct = am / at * 100 if at else 0
        print(f"  {qt:<10} {bm}/{bt} ({b_pct:.0f}%) → {am}/{at} ({a_pct:.0f}%)  "
              f"[{_signed(a_pct - b_pct, '.0f')} pts]")
    print()
    if b_traj is not None and a_traj is not None:
        print(f"Trajectory F1 (avg): {b_traj:.3f} → {a_traj:.3f}  "
              f"[{_signed(a_traj - b_traj, '+.3f')}]")
    judge_present = any(b is not None and a is not None
                        for b, a in judge_deltas.values())
    if judge_present:
        print("Judge scores (0-5):")
        for k, (b, a) in judge_deltas.items():
            if b is None or a is None:
                continue
            print(f"  {k:<22} {b:.2f} → {a:.2f}  [{_signed(a - b, '+.2f')}]")
    print()
    print(f"Improvements (newly passing): {len(improvements)}")
    for line in _format_flip_rows(improvements):
        print(line)
    print()
    print(f"Regressions  (newly failing): {len(regressions)}")
    for line in _format_flip_rows(regressions):
        print(line)
    if only_before or only_after:
        print()
        print(f"Coverage mismatch — only in BEFORE: {len(only_before)}, "
              f"only in AFTER: {len(only_after)}")


def _print_markdown(before_path, after_path, b_match, b_total, a_match, a_total,
                    delta_pts, all_types, b_per_type, a_per_type,
                    b_traj, a_traj, judge_deltas,
                    improvements, regressions, only_before, only_after):
    print(f"## Eval comparison\n")
    print(f"- **Before**: `{before_path.name}` ({b_total} queries)")
    print(f"- **After**: `{after_path.name}` ({a_total} queries)\n")
    print("### Decision accuracy\n")
    print("| Slice | Before | After | Δ |")
    print("|---|---|---|---|")
    print(f"| **Overall** | {_pct(b_match, b_total)} | {_pct(a_match, a_total)} "
          f"| {_signed(delta_pts)} pts |")
    for qt in all_types:
        bm, bt = b_per_type.get(qt, (0, 0))
        am, at = a_per_type.get(qt, (0, 0))
        b_pct = bm / bt * 100 if bt else 0
        a_pct = am / at * 100 if at else 0
        print(f"| {qt} | {bm}/{bt} ({b_pct:.0f}%) | {am}/{at} ({a_pct:.0f}%) "
              f"| {_signed(a_pct - b_pct, '.0f')} pts |")
    if b_traj is not None and a_traj is not None:
        print(f"\n### Other metrics\n")
        print(f"- Trajectory F1: **{b_traj:.3f} → {a_traj:.3f}** "
              f"({_signed(a_traj - b_traj, '+.3f')})")
    if improvements:
        print(f"\n### ✅ Newly passing ({len(improvements)})\n")
        for b, a in improvements:
            print(f"- `{a['id']}` ({a['query_type']}) — "
                  f"`{b.get('actual_decision') or 'ERR'}` → "
                  f"`{a.get('actual_decision') or 'ERR'}` "
                  f"(expected `{a['expected_decision']}`)")
    if regressions:
        print(f"\n### ❌ Newly failing ({len(regressions)})\n")
        for b, a in regressions:
            print(f"- `{a['id']}` ({a['query_type']}) — "
                  f"`{b.get('actual_decision') or 'ERR'}` → "
                  f"`{a.get('actual_decision') or 'ERR'}` "
                  f"(expected `{a['expected_decision']}`)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("before", nargs="?", type=Path,
                    help="baseline JSONL (defaults to second-most-recent in eval/reports/)")
    ap.add_argument("after", nargs="?", type=Path,
                    help="new run JSONL (defaults to most-recent in eval/reports/)")
    ap.add_argument("--markdown", action="store_true",
                    help="emit markdown tables (paste into PR descriptions)")
    args = ap.parse_args()

    if args.before is None or args.after is None:
        before, after = _auto_pick_latest_two()
    else:
        before, after = args.before, args.after

    compare(before, after, as_markdown=args.markdown)


if __name__ == "__main__":
    main()
