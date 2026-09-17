"""Single source of truth for which Groq model each stage runs on.

Why this module exists
----------------------
Groq deprecates hosted models without notice, and every time it happens the
model ID is hardcoded as a default in ~9 different files, so the fix is a
scavenger hunt. This has now bitten the project three times:

  1. `meta-llama/llama-4-scout-17b-16e-instruct` was decommissioned (523e86cb)
  2. the replacement `llama-3.3-70b-versatile` + `llama-3.1-8b-instant` were
     decommissioned along with the *entire* Llama family
  3. ...whatever is next

Now every call site imports from here, so the next deprecation is a one-line
change plus `python -m scripts.doctor` to confirm.

Rate buckets
------------
Groq rate limits are **per model**, not per organization — verified empirically:
burning `openai/gpt-oss-120b` down to 4992 remaining tokens left
`openai/gpt-oss-20b` untouched at 7923. Limits are 8000 TPM / 1000 RPD each.

That makes the model choice a load-balancing decision, not just a quality one.
Three hot paths therefore get three independent buckets:

  - planner + synthesizer + brief  -> AGENT_MODEL     (gpt-oss-120b)
  - executor loop                  -> EXECUTOR_MODEL  (gpt-oss-20b)
  - review_qa RAG + /chat          -> GROQ_MODEL      (qwen3.8-27b)

`review_qa` needs its own bucket specifically because the executor *calls* it
during an agent run. Sharing would put ~5 calls from a single agent run through
one 8000 TPM limit, which is what produced the 429s in
eval/reports/2026-07-18-full.md.

Reasoning effort
----------------
The gpt-oss models are reasoning models — they emit hidden reasoning tokens
before answering. Measured on an identical prompt, `reasoning_effort="low"`
cut total tokens from 280 to 171 (~40%), which cuts both latency and pressure
against the 8000 TPM cap. Tool selection and summarization don't need deep
reasoning; the user-facing recommendation does, so those stages get "medium".
"""
import os

from dotenv import load_dotenv

load_dotenv()

# Env var names are unchanged from before this module existed, so existing
# .env files and the Render dashboard keep working without edits.
_ENV_VARS = {
    "agent": "AGENT_MODEL",
    "executor": "EXECUTOR_MODEL",
    "rag": "GROQ_MODEL",
    "intent": "INTENT_LLM_MODEL",
}

# Current defaults. Every ID here was verified present in Groq's live model
# list and exercised against this repo's actual client code — instructor
# structured output for agent/intent, ChatGroq tool-calling for executor.
DEFAULT_MODELS = {
    "agent": "openai/gpt-oss-120b",
    "executor": "openai/gpt-oss-20b",
    "rag": "qwen/qwen3.8-27b",
    "intent": "openai/gpt-oss-20b",
}

REASONING_EFFORT = {
    "agent": "medium",      # synthesizer + brief — user-facing narrative
    "planner": "low",       # classify query, pick tools from a fixed set of 5
    "executor": "low",      # "which tool next?" — many short calls
    "rag": "low",           # summarize retrieved review chunks
    "intent": "low",        # constrained classification
}

# Ordered fallback chains — the durability mechanism.
#
# A single pinned model is always one deprecation away from a production
# outage; that is exactly how this app broke three times. Each stage instead
# gets an ordered list: the configured/default model first, then alternates.
# `resilient_call` walks the chain when a model is GONE (404) or RATE-LIMITED
# (429), so a deprecation degrades quality instead of taking the app down.
#
# Only these four Groq models support BOTH tool-calling and structured output
# (surveyed live — allam-2-7b, groq/compound and groq/compound-mini reject
# `tools` outright, and the whisper/orpheus/prompt-guard families are not
# chat models). Fallbacks are ordered to land on a DIFFERENT rate bucket
# where possible, so a 429 actually gets relief.
#
# ⚠️ Do NOT reorder this dict on the strength of one observed failure.
# Attempted and reverted 2026-09-17: qwen returned XML-style tool-call syntax
# for one long Synthesizer prompt, which looked like grounds to drop it from
# the agent chain in favour of `openai/gpt-oss-safeguard-20b`. A direct A/B
# against the *real* `Recommendation` schema then showed the opposite — qwen
# produced valid JSON and safeguard-20b was the one that 400'd, emitting
# `evidence` objects with `source`/`description` instead of the schema's
# `snippet`/`relevance`. Every one of these models fails this schema
# sometimes; none fails it always. `python -m scripts.doctor --probe`
# exercises the real schema against every configured model — run it and read
# the pass counts before editing this.
FALLBACK_CHAINS = {
    "agent":    ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
    "executor": ["openai/gpt-oss-20b", "openai/gpt-oss-safeguard-20b", "qwen/qwen3.8-27b"],
    "rag":      ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"],
    "intent":   ["openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b"],
}

# What to tell the user when a configured model has been decommissioned.
# scripts/doctor.py reads this to print an actionable suggestion instead of
# just reporting that the model is gone.
KNOWN_GOOD = dict(DEFAULT_MODELS)


def model_chain(stage: str) -> list[str]:
    """Models to try for `stage`, in order: configured pin first, then fallbacks.

    The configured model always leads even if it is not in FALLBACK_CHAINS —
    an operator pinning something via env must still get what they asked for.
    """
    primary = _model_for(stage)
    chain = [primary]
    for m in FALLBACK_CHAINS.get(stage, []):
        if m not in chain:
            chain.append(m)
    return chain


# Error signatures worth failing over for. Anything else (a bad API key, a
# malformed request we built) is a real bug and must surface immediately
# rather than being retried against three models in a row.
_MODEL_GONE = ("model_not_found", "does not exist or you do not have access")
_RATE_LIMITED = ("rate_limit_exceeded", "rate limit reached", "request too large")

# Groq rejects a tool call it cannot use with a 400 whose code is
# `tool_use_failed`. It is a *generation* problem, not a bad request — the
# model was asked for a valid schema and produced something else. Three
# flavours observed on this repo's `Recommendation` schema:
#
#   1. Almost-valid JSON — escaped quotes inside an already-quoted string
#      ("Failed to parse tool call arguments as JSON").
#   2. Valid JSON, wrong shape — "Tool call validation failed: ... missing
#      properties: 'snippet', 'relevance'".
#   3. A different tool-call *syntax* entirely: `<tool_call><function=...>
#      <parameter=...>` instead of JSON arguments.
#
# All three are stochastic on a given model/prompt pair, which is what makes
# the same-model retry below worth it. Measured 3.3% of eval queries (1/30).
# Whichever flavour it is, the agent run dies visibly.
#
# It is NOT caught by instructor's own `max_retries`, which is already 2 at
# every call site. instructor's retry predicate is
# `retry_if_exception_type((ValidationError, json.JSONDecodeError,
# AsyncValidationError, ResponseParsingError))`, and a `tool_use_failed` 400
# is a `BadRequestError` — so tenacity makes exactly one attempt and reraises
# ("Max retries exceeded. Total attempts: 1" in the logs). instructor only
# retries JSON that parses and then fails ITS validation; Groq validates
# server-side and rejects first. Bumping max_retries does nothing.
_TOOL_CALL_MALFORMED = (
    "tool_use_failed",
    "failed to parse tool call arguments",
    "tool call validation failed",
)


def _failover_reason(err: Exception) -> str | None:
    """Return why `err` warrants trying the next model, or None to re-raise."""
    # Opt-out for callers that run their own retry policy for a signature we
    # also match — currently the executor node, which retries malformed tool
    # calls per model and then degrades gracefully. Without this, its
    # exhausted-retries error would match below and be retried all over again
    # on every model in the chain.
    if getattr(err, "llm_no_failover", False):
        return None
    text = str(err).lower()
    if any(sig in text for sig in _MODEL_GONE):
        return "decommissioned"
    if any(sig in text for sig in _RATE_LIMITED):
        return "rate-limited"
    if any(sig in text for sig in _TOOL_CALL_MALFORMED):
        return "emitting malformed tool calls"
    return None


# How many times to re-run the SAME model before advancing the chain.
#
# A malformed tool call is stochastic — the identical request often succeeds on
# a second attempt — so one cheap same-model retry is the highest-value
# recovery available, and it is strictly better than failing over, because no
# model in the chain is reliably better at this schema. Decommissioning and
# rate limits are not stochastic: retrying the same model there only adds
# latency, so they advance at once.
#
# One retry, not three: every attempt spends the per-model token budget
# (200k tokens/day, 8k/min on the free tier), and burning it here makes the
# NEXT query likelier to 429. That cascade is real — it is what turned a
# 15-query verification run into four rate-limit failures on 2026-09-17.
_SAME_MODEL_RETRIES = {"emitting malformed tool calls": 1}


def resilient_call(stage: str, fn):
    """Run `fn(model_id)` against the stage's chain until one succeeds.

    `fn` takes a model id and performs the actual LLM call. On a decommissioned
    or rate-limited model, or one that returned an unusable tool call, we move
    to the next candidate; any other exception propagates untouched. If every
    model fails, the LAST exception is raised so the caller sees a real
    provider error rather than a synthetic one.

    This is what keeps a Groq deprecation from becoming an outage: the app
    silently degrades to the next model and logs loudly enough that
    `scripts/doctor.py` gets run.

    Worst case is bounded by `len(chain)` attempts plus one extra per model for
    a malformed tool call — 6 calls for a 3-model chain. That ceiling is only
    reached on a path that would otherwise have failed outright.
    """
    chain = model_chain(stage)
    last: Exception | None = None
    i = 0
    retries_used = 0
    while i < len(chain):
        model = chain[i]
        try:
            return fn(model)
        except Exception as e:  # noqa: BLE001 — provider exception types vary
            reason = _failover_reason(e)
            if reason is None:
                raise
            last = e
            if retries_used < _SAME_MODEL_RETRIES.get(reason, 0):
                retries_used += 1
                print(
                    f"[llm_config] {stage}: {model} is {reason}; "
                    f"retrying the same model (attempt {retries_used + 1})."
                )
                continue
            if i == len(chain) - 1:
                raise
            nxt = chain[i + 1]
            print(
                f"[llm_config] {stage}: {model} is {reason}; "
                f"falling back to {nxt}. Run `python -m scripts.doctor`."
            )
            i += 1
            retries_used = 0
    if last:
        raise last
    raise RuntimeError(f"no models configured for stage {stage!r}")

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"


def api_key() -> str | None:
    """Read the key at call time, not import time, so tests can patch it."""
    return os.getenv("GROQ_API_KEY")


def _model_for(stage: str) -> str:
    return os.getenv(_ENV_VARS[stage], DEFAULT_MODELS[stage])


def agent_model() -> str:
    """Planner, synthesizer, executive brief, eval baselines."""
    return _model_for("agent")


def executor_model() -> str:
    """The executor's tool-selection loop."""
    return _model_for("executor")


def rag_model() -> str:
    """review_qa RAG chain and the v1 /chat endpoint."""
    return _model_for("rag")


def intent_model() -> str:
    """Intent-classification LLM fallback and offline transcript generation."""
    return _model_for("intent")


def reasoning_effort(stage: str) -> str:
    return REASONING_EFFORT.get(stage, "low")


def configured_models() -> dict[str, str]:
    """Stage -> model ID for every stage. Used by /health and the doctor."""
    return {
        "agent": agent_model(),
        "executor": executor_model(),
        "rag": rag_model(),
        "intent": intent_model(),
    }


def groq_client():
    """Shared `instructor`-wrapped Groq client for structured-output calls.

    Previously duplicated in six places. Not cached — instructor wraps a
    thread-safe httpx client, but callers that want a singleton still apply
    their own lru_cache.
    """
    import instructor
    from groq import Groq

    return instructor.from_groq(Groq(api_key=api_key()))


def thought_text(message) -> str:
    """Extract an executor "thought" from a LangChain AIMessage.

    Reasoning models put their visible answer in `.content` but their reasoning
    trace in `additional_kwargs["reasoning_content"]`, and when a turn is a pure
    tool call `.content` comes back as an empty string. The old Llama models put
    their rationale directly in `.content`, so any caller that reads `.content`
    alone now silently renders nothing.

    Returns `.content` when present, else the reasoning trace, else "".
    """
    content = getattr(message, "content", None)
    if content:
        return str(content)
    extra = getattr(message, "additional_kwargs", None) or {}
    return str(extra.get("reasoning_content") or "")
