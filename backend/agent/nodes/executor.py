"""Executor node — picks the next tool call based on plan + observations.

This node owns the loop. Each invocation:
  - Looks at the remaining plan and what's been called so far
  - Asks the LLM to emit ONE tool call (the next step) OR a finishing message
  - Returns updated state; the routing edge in graph.py decides whether
    to invoke ToolNode (tool call present) or move on to Synthesizer.

The Executor also handles the optional re-plan loop triggered by a
low-confidence Synthesizer output.
"""
import os

from langchain_core.messages import AIMessage, SystemMessage
from langchain_groq import ChatGroq

from ..prompts import executor_system_prompt
from ..schemas import AgentState


def _model() -> str:
    # The executor makes several short "which tool next?" calls per question,
    # so it runs on its own smaller/faster model (and its own Groq daily
    # bucket) to keep the 70B AGENT_MODEL budget free for the planner and
    # synthesizer. Still Llama-family, so the JSON tool_calls tuning below
    # stays valid. Independent default — does NOT fall back to AGENT_MODEL,
    # so the bucket split holds even when only AGENT_MODEL is configured.
    return os.getenv("EXECUTOR_MODEL", "llama-3.1-8b-instant")


def make_executor_node(tools):
    """Closure that binds tools to the executor LLM at graph-build time."""
    llm = ChatGroq(model=_model(), temperature=0.1, max_tokens=1024)
    # parallel_tool_calls=False: serial tool calls only — keeps Llama-family
    # models on the JSON tool_calls path instead of slipping into
    # Llama-native XML function syntax.
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

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
        response = llm_with_tools.invoke(messages)

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
