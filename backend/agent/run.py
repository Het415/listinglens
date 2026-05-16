"""CLI entry for the ListingLens Copilot agent.

Usage:
    python -m backend.agent.run --asin B07VYP6WSY "Should I launch a glass variant?"
    python -m backend.agent.run --asin B08XPWDSWW "Why are returns spiking?" --pretty
"""
import argparse
import json
import sys
import time

from .graph import run_agent


def _pretty_print(out_dict: dict) -> None:
    rec = out_dict["recommendation"]
    trace = out_dict["trace"]

    print()
    print("=" * 70)
    print(f"  RECOMMENDATION: {rec['decision'].upper()}  (confidence {rec['confidence']:.0%})")
    print("=" * 70)
    print()
    print(rec["summary"])
    print()

    if rec["reasoning_steps"]:
        print("REASONING")
        for i, step in enumerate(rec["reasoning_steps"], 1):
            print(f"  {i}. {step}")
        print()

    if rec["evidence"]:
        print("EVIDENCE")
        for e in rec["evidence"]:
            print(f"  [{e['tool']:>20}] (rel={e['relevance']:.2f}) {e['snippet'][:140]}")
        print()

    if rec["risks"]:
        print("RISKS")
        for r in rec["risks"]:
            print(f"  - {r}")
        print()

    if rec["suggested_next_actions"]:
        print("SUGGESTED NEXT ACTIONS")
        for a in rec["suggested_next_actions"]:
            print(f"  - {a}")
        print()

    print("TRACE")
    print(f"  tool calls: {trace['n_tool_calls']}")
    print(f"  iterations: {trace['iterations']}")
    print(f"  tools called: {', '.join(trace['tools_called']) or '(none)'}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ListingLens Copilot CLI",
    )
    parser.add_argument("--asin", required=True, help="10-character ASIN")
    parser.add_argument("query", help="Natural-language question")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print output instead of JSON")
    args = parser.parse_args()

    t0 = time.time()
    try:
        result = run_agent(asin=args.asin, query=args.query)
    except Exception as e:
        print(f"Agent failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    elapsed = time.time() - t0
    out = result.model_dump()

    if args.pretty:
        _pretty_print(out)
        print(f"(completed in {elapsed:.1f}s)")
    else:
        print(json.dumps(out, indent=2))
        print(f"\n(completed in {elapsed:.1f}s)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
