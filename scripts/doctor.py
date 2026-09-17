"""Preflight check for the LLM + retrieval stack.

    python -m scripts.doctor
    python -m scripts.doctor --probe     # also make one real call per model

Why this exists
---------------
Groq has decommissioned models under this project three times. Each time the
symptom was indirect and misleading: the Copilot 404'd on the planner's first
call, or the RAG chain 404'd *after* retrieval succeeded, which looks for all
the world like "retrieval is broken."

This script turns that 15-minute diagnosis into a 5-second one. It answers,
in order: is the key set, are the configured models still live, and are the
FAISS indexes intact and rating-balanced.

Exits non-zero on any hard failure so CI can gate on it.
"""
from __future__ import annotations

import argparse
import os
import sys

# Repo root on sys.path so `python -m scripts.doctor` works from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.llm_config import (  # noqa: E402
    KNOWN_GOOD,
    _ENV_VARS,
    api_key,
    configured_models,
    model_chain,
    reasoning_effort,
)

OK = "\033[32mOK\033[0m"
BAD = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

# Stages that intentionally share a rate bucket. The executor and the intent
# fallback collide by design: intent fires only below the sklearn confidence
# threshold, on single short messages, and never inside a Copilot request.
ALLOWED_BUCKET_SHARING = {("executor", "intent")}


def _header(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")
    print("-" * len(title))


def check_key() -> bool:
    _header("API key")
    if api_key():
        print(f"  [{OK}] GROQ_API_KEY is set")
        return True
    print(f"  [{BAD}] GROQ_API_KEY is not set — every LLM path will fail.")
    print("         Add it to .env (see .env.example).")
    return False


def live_model_ids() -> set[str] | None:
    """Fetch Groq's current catalog. None if we couldn't ask."""
    try:
        from groq import Groq

        return {m.id for m in Groq(api_key=api_key()).models.list().data}
    except Exception as e:  # noqa: BLE001
        print(f"  [{WARN}] could not list Groq models ({type(e).__name__}: {e})")
        return None


def check_models(live: set[str] | None) -> bool:
    _header("Configured models")
    configured = configured_models()
    ok = True

    for stage, model in configured.items():
        env_var = _ENV_VARS[stage]
        effort = reasoning_effort(stage)
        if live is None:
            print(f"  [{WARN}] {stage:9s} {model:26s} ({env_var}, effort={effort}) — unverified")
            continue
        if model in live:
            print(f"  [{OK}] {stage:9s} {model:26s} ({env_var}, effort={effort})")
        else:
            ok = False
            print(f"  [{BAD}] {stage:9s} {model:26s} ({env_var}) — NOT AVAILABLE ON GROQ")
            suggestion = KNOWN_GOOD.get(stage)
            if suggestion and suggestion in live:
                print(f"         fix: set {env_var}={suggestion} in .env and render.yaml")
            else:
                tool_capable = sorted(
                    m for m in live
                    if not m.startswith(("whisper", "canopylabs"))
                    and "prompt-guard" not in m
                )
                print(f"         live candidates: {', '.join(tool_capable)}")

    # Fallback chains are what keep a deprecation from becoming an outage.
    # A stage is only at risk if EVERY model in its chain is gone.
    _header("Fallback chains")
    for stage in configured:
        chain = model_chain(stage)
        if live is None:
            print(f"  [{WARN}] {stage:9s} {' -> '.join(chain)} (unverified)")
            continue
        alive = [m for m in chain if m in live]
        rendered = " -> ".join(
            m if m in live else f"\033[31m{m}\033[0m" for m in chain
        )
        if not alive:
            ok = False
            print(f"  [{BAD}] {stage:9s} {rendered}")
            print("         EVERY model in this chain is gone — this stage WILL fail")
        elif len(alive) == len(chain):
            print(f"  [{OK}] {stage:9s} {rendered}")
        else:
            print(f"  [{WARN}] {stage:9s} {rendered}")
            print(f"         {len(alive)}/{len(chain)} live — still serving, but "
                  f"update FALLBACK_CHAINS in src/llm_config.py")

    # Rate limits are per-model, so two stages on one model share a bucket.
    _header("Rate buckets")
    by_model: dict[str, list[str]] = {}
    for stage, model in configured.items():
        by_model.setdefault(model, []).append(stage)

    for model, stages in sorted(by_model.items()):
        if len(stages) == 1:
            print(f"  [{OK}] {model:26s} <- {stages[0]}")
            continue
        pair = tuple(sorted(stages))
        if pair in ALLOWED_BUCKET_SHARING or len(stages) == 2 and pair in ALLOWED_BUCKET_SHARING:
            print(f"  [{OK}] {model:26s} <- {', '.join(stages)} (sharing is intentional)")
        else:
            print(f"  [{WARN}] {model:26s} <- {', '.join(stages)} share one 8000 TPM bucket")
            print("         these stages can run concurrently; expect 429s under load")
    return ok


# How many times --probe asks each model for the real Recommendation schema.
#
# Must be >1. A single attempt cannot distinguish "this model can't do it"
# from "this model got it wrong once", and getting it wrong once is the
# normal, expected behaviour here — see STRUCTURED_OUTPUT_NOTE below.
SCHEMA_PROBE_ATTEMPTS = 2

# Why the probes never fail the run.
#
# A rate limit says nothing about a model's capability, and the free tier's
# 200k tokens/day is routinely spent by one eval run — so failing the whole
# doctor on a 429 would make it useless in exactly the situation where you
# want to run it. And schema flakiness is not actionable either: see the note.
STRUCTURED_OUTPUT_NOTE = (
    "Probes are INFORMATIONAL — they never fail the run.\n"
    "  Every model here fails this schema sometimes and none fails it always, so\n"
    "  a score below {n}/{n} is NOT grounds to drop a model from FALLBACK_CHAINS.\n"
    "  `resilient_call` retries the same model once before failing over, which is\n"
    "  what these attempts simulate. Two caveats when reading the numbers:\n"
    "  a `rate-limited` flavour is inconclusive, not a failure; and the probe\n"
    "  prompt carries no tool evidence, so models have to invent the `evidence`\n"
    "  list and get its shape wrong more often here than in a real agent run."
)


def _tool_call_flavour(err: Exception) -> str:
    """Name the way a model got a tool call wrong, for the probe's output.

    Three distinct flavours show up behind the single `tool_use_failed` code,
    and they mean different things — see the note on _TOOL_CALL_MALFORMED in
    src/llm_config.py.
    """
    text = str(err).lower()
    if "<tool_call>" in text or "<function=" in text:
        return "XML tool-call syntax instead of JSON"
    if "tool call validation failed" in text:
        return "valid JSON, wrong schema shape"
    if "failed to parse tool call arguments" in text:
        return "malformed JSON arguments"
    if "rate_limit_exceeded" in text or "rate limit reached" in text:
        return "rate-limited (inconclusive — retry when the budget resets)"
    return type(err).__name__


def probe_models() -> bool:
    """One real tool-call and one structured call per distinct model.

    The structured-output probe uses the **real** `Recommendation` schema, not
    a toy stand-in. That distinction is the whole point: a 2-field model
    passes on every Groq model here, while the 8-field `Recommendation` — with
    a nested `evidence` list — is what actually fails in production with
    `400 tool_use_failed`. Probing the toy schema reported all-clear on a
    model that could not serve a single real Synthesizer call.
    """
    _header("Live probes")

    from backend.agent.schemas import Recommendation

    from src.llm_config import groq_client

    for model in sorted(set(configured_models().values())):
        # Structured output — the instructor path (planner/synthesizer/brief/intent).
        #
        # The prompt must genuinely require extraction. Asking for a single
        # word tempts the model to answer in plain text, which Groq rejects
        # with "model did not call a tool" — a false alarm about the model
        # rather than a real capability gap.
        passes, flavours = 0, []
        for _ in range(SCHEMA_PROBE_ATTEMPTS):
            try:
                groq_client().chat.completions.create(
                    model=model,
                    response_model=Recommendation,
                    max_retries=1,
                    max_tokens=2048,
                    messages=[{
                        "role": "user",
                        "content": (
                            "Returns are up 40% and reviews cite battery failure. "
                            "Give a go/no-go decision and your confidence."
                        ),
                    }],
                )
                passes += 1
            except Exception as e:  # noqa: BLE001
                flavours.append(_tool_call_flavour(e))

        label = f"Recommendation schema {passes}/{SCHEMA_PROBE_ATTEMPTS}"
        detail = ", ".join(sorted(set(flavours)))
        if passes == SCHEMA_PROBE_ATTEMPTS:
            print(f"  [{OK}] {model:26s} {label}")
        else:
            print(f"  [{WARN}] {model:26s} {label} — {detail}")

        # tool calling (the ChatGroq path: executor)
        try:
            from langchain_groq import ChatGroq

            def review_qa(question: str) -> str:
                """Ask a question about product reviews."""
                return ""

            llm = ChatGroq(model=model, temperature=0, max_tokens=2048)
            res = llm.bind_tools([review_qa], parallel_tool_calls=False).invoke(
                "Find out what reviewers complain about. Use the tool."
            )
            if res.tool_calls:
                print(f"  [{OK}] {model:26s} tool calling")
            else:
                print(f"  [{WARN}] {model:26s} returned no tool call "
                      f"(finish may have been truncated by max_tokens)")
        except Exception as e:  # noqa: BLE001
            print(f"  [{WARN}] {model:26s} tool calling — {_tool_call_flavour(e)}")

    print("\n  " + STRUCTURED_OUTPUT_NOTE.format(n=SCHEMA_PROBE_ATTEMPTS))
    # Always True by design — see the comment on STRUCTURED_OUTPUT_NOTE. The
    # return value is kept so main()'s `ok = ... and probe_models()` wiring
    # does not need a special case.
    return True


def check_vectorstores() -> bool:
    """FAISS indexes present, non-empty, and covering every rating."""
    _header("Vectorstores")
    from pathlib import Path

    from src.rag_chatbot import PROCESSED_DIR

    dirs = sorted(Path(PROCESSED_DIR).glob("vectorstore_*"))
    if not dirs:
        print(f"  [{BAD}] no vectorstore_* directories in {PROCESSED_DIR}")
        return False

    ok = True
    incomplete = []
    for d in dirs:
        if not ((d / "index.faiss").exists() and (d / "index.pkl").exists()):
            ok = False
            incomplete.append(d.name)
    if incomplete:
        print(f"  [{BAD}] missing index.faiss/index.pkl: {', '.join(incomplete)}")
        print("         FAISS.save_local writes both; a partial dir is not a valid cache")

    # Load one index and confirm ratings are balanced. A store rebuilt from a
    # plain head(100) of the rating-sorted CSVs contains only 1- and 2-star
    # chunks, which silently zeroes any 5-star filtered query.
    try:
        from langchain_community.vectorstores import FAISS

        from src.rag_chatbot import _get_embeddings

        sample = dirs[0]
        vs = FAISS.load_local(str(sample), _get_embeddings(), allow_dangerous_deserialization=True)
        ratings: dict[int, int] = {}
        for doc in vs.docstore._dict.values():
            r = doc.metadata.get("rating")
            if r is not None:
                ratings[int(r)] = ratings.get(int(r), 0) + 1
        print(f"  [{OK}] {len(dirs)} stores; {sample.name} has {vs.index.ntotal} vectors")
        if ratings:
            spread = dict(sorted(ratings.items()))
            if len(ratings) < 3:
                ok = False
                print(f"  [{BAD}] {sample.name} rating spread {spread} — index looks "
                      f"rebuilt from an unstratified head() slice")
            else:
                print(f"  [{OK}] rating spread {spread}")
    except Exception as e:  # noqa: BLE001
        print(f"  [{WARN}] could not inspect {dirs[0].name} ({type(e).__name__}: {e})")

    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true",
                    help="make one real structured + tool call per model (uses quota)")
    ap.add_argument("--skip-vectorstores", action="store_true",
                    help="skip FAISS checks (they load torch, which is slow)")
    args = ap.parse_args()

    print("\033[1mListingLens doctor\033[0m")
    results = [check_key()]
    live = live_model_ids() if results[0] else None
    results.append(check_models(live))
    if args.probe and results[0]:
        results.append(probe_models())
    if not args.skip_vectorstores:
        results.append(check_vectorstores())

    print()
    if all(results):
        print(f"[{OK}] all checks passed")
        return 0
    print(f"[{BAD}] one or more checks failed — see above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
