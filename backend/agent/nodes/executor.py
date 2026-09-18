"""Executor node — picks the next tool call based on plan + observations.

This node owns the loop. Each invocation:
  - Looks at the remaining plan and what's been called so far
  - Asks the LLM to emit ONE tool call (the next step) OR a finishing message
  - Returns updated state; the routing edge in graph.py decides whether
    to invoke ToolNode (tool call present) or move on to Synthesizer.

The Executor also handles the optional re-plan loop triggered by a
low-confidence Synthesizer output.
"""
from langchain_core.messages import AIMessage, SystemMessage
from langchain_groq import ChatGroq

from src.llm_config import is_provider_capacity_error, reasoning_effort, resilient_call

from ..prompts import executor_system_prompt
from ..schemas import AgentState


# Groq rejects a malformed tool call server-side with a 400 whose code is
# `tool_use_failed` ("Failed to parse tool call arguments as JSON"). That is a
# stochastic generation slip, not a bug in the request: the same query can
# succeed on the next attempt. Retrying the turn recovers it; without a retry
# a single bad generation aborts the whole agent run.
TOOL_CALL_RETRIES = 3


def _invoke_with_retry(bind_for, messages):
    """Invoke the bound LLM, retrying transient malformed-tool-call 400s.

    `bind_for(model_id)` returns a tools-bound ChatGroq for that model, so a
    decommissioned or rate-limited model fails over to the next candidate via
    `resilient_call` while the malformed-tool-call retry happens per model.

    Falls back to a content-only AIMessage after the last attempt so the graph
    routes on to the Synthesizer with whatever evidence it already gathered,
    rather than failing the request outright.
    """
    last_err: Exception | None = None

    def attempt_with(model: str):
        nonlocal last_err
        for attempt in range(1, TOOL_CALL_RETRIES + 1):
            try:
                return bind_for(model).invoke(messages)
            except Exception as e:  # noqa: BLE001 — provider exception types vary
                text = str(e)
                # Let resilient_call see 404s/429s so it can switch models.
                if "tool_use_failed" not in text and "tool call" not in text.lower():
                    raise
                last_err = e
                print(
                    f"[executor] malformed tool call from {model} "
                    f"(attempt {attempt}/{TOOL_CALL_RETRIES}): {type(e).__name__}"
                )
        # Exhausted retries on THIS model without a provider-level error.
        raise _MalformedToolCalls(str(last_err))

    reason = "unparseable tool calls on every model"
    try:
        return resilient_call("executor", attempt_with)
    except _MalformedToolCalls:
        # Every retry on every model produced tool-call JSON Groq rejected.
        pass
    except Exception as e:  # noqa: BLE001 — provider exception types vary
        # The chain is exhausted for a reason that is not our fault: every
        # model rate-limited, or every model decommissioned. Degrade for the
        # same reason the malformed-tool-call path does — the evidence already
        # gathered is still worth synthesizing, and losing the whole run costs
        # the user everything the agent had proved.
        #
        # This branch used to be a bare `raise`, so a rate-limited chain killed
        # the request outright. Measured on the 2026-09-17 judged run:
        # improve_006, improve_008 and improve_010 all died here, each with
        # tools_called == [] — the run never reached the Synthesizer, so the
        # Synthesizer's own fallback had nothing to catch. Three of thirty
        # queries, all from one exhausted daily token budget.
        #
        # Anything else still raises. An auth failure or a bug in the request
        # we built must surface loudly: degrading it would turn a total outage
        # into a stream of plausible "partial answers" that nobody looks into.
        if not is_provider_capacity_error(e):
            raise
        last_err = e
        reason = f"provider capacity exhausted ({type(e).__name__})"

    print(f"[executor] giving up on tool calls — {reason}; synthesizing from evidence so far")
    return AIMessage(
        content=(
            "I was unable to issue a further tool call. Synthesize a "
            "recommendation from the evidence gathered so far, and note the "
            "missing step as an evidence gap."
        ),
        name="executor_degraded",
        additional_kwargs={"tool_call_error": str(last_err)[:500]},
    )


class _MalformedToolCalls(RuntimeError):
    """Every retry on a model produced unparseable tool-call JSON.

    `llm_no_failover` tells `resilient_call` to re-raise instead of walking the
    fallback chain. This class's message embeds the original Groq error, which
    contains `tool_use_failed` — a signature `resilient_call` now fails over
    for. Without the opt-out, exhausting TOOL_CALL_RETRIES here would hand the
    error back for another full chain walk, so a single stuck executor turn
    would cost 3 models x 3 attempts instead of 3, on a path whose whole point
    is to degrade quickly and let the Synthesizer work with what it has.
    """

    llm_no_failover = True


def make_executor_node(tools):
    """Closure that binds tools to the executor LLM at graph-build time.

    The executor makes several short "which tool next?" calls per question, so
    it runs on a smaller/faster model with its own Groq rate bucket, keeping
    the flagship AGENT_MODEL budget free for the planner and synthesizer.
    Groq limits are per-model (8000 TPM each), so this split is what keeps a
    single agent run from rate-limiting itself. See src/llm_config.py.

    reasoning_effort="low": these are reasoning models, and picking the next
    tool from a fixed set of 5 does not need a long reasoning trace. Keeping it
    low cuts both latency and token burn against the per-model cap.
    """
    # Built per model (and cached) so the fallback chain can swap models
    # mid-run without rebuilding the graph.
    #
    # max_tokens=2048 (was 1024): a reasoning model's hidden trace is billed
    # against the completion budget, so too tight a cap can spend the whole
    # allowance thinking and return finish_reason="length" with NO tool call —
    # which looks like a broken agent rather than a truncated response.
    #
    # parallel_tool_calls=False: serial tool calls only. The graph already
    # loops the executor, so serial is functionally equivalent, and it keeps
    # the one-tool-call-per-turn contract the routing edge in graph.py expects.
    _bound: dict[str, object] = {}

    def bind_for(model: str):
        if model not in _bound:
            llm = ChatGroq(
                model=model,
                temperature=0.1,
                max_tokens=2048,
                reasoning_effort=reasoning_effort("executor"),
                request_timeout=60,
                max_retries=1,
            )
            _bound[model] = llm.bind_tools(tools, parallel_tool_calls=False)
        return _bound[model]

    def execute_node(state: AgentState) -> dict:
        is_replan = state.get("replans_done", 0) > 0 and len(state.get("tools_called", [])) > 0
        sys_prompt = executor_system_prompt(
            asin=state["asin"],
            product_name=state.get("product_name"),
            plan=state.get("plan", []),
            tools_called=state.get("tools_called", []),
            is_replan=is_replan,
        )

        # Strip out the planner's bookkeeping AIMessage if present — the
        # executor LLM only needs the system instructions + question +
        # tool history (HumanMessage + ToolMessage chain).
        history = [
            m for m in state.get("messages", [])
            if not (isinstance(m, AIMessage) and getattr(m, "name", None) == "planner")
        ]

        messages = [SystemMessage(content=sys_prompt), *history]
        response = _invoke_with_retry(bind_for, messages)

        # Track tool calls for the trace + dedup
        new_tools_called = list(state.get("tools_called", []))
        new_plan = list(state.get("plan", []))
        new_iterations = state.get("iterations", 0)

        if isinstance(response, AIMessage) and response.tool_calls:
            for tc in response.tool_calls:
                new_tools_called.append(tc["name"])
                # consume from plan if matching
                if tc["name"] in new_plan:
                    new_plan.remove(tc["name"])
                new_iterations += 1

        return {
            "messages": [response],
            "tools_called": new_tools_called,
            "plan": new_plan,
            "iterations": new_iterations,
        }

    return execute_node
