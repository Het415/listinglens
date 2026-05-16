"""Baseline agents for the eval harness.

Two baselines:
  - no_tool: a single LLM call with no tools. The "minimum useful" floor.
  - single_tool: an agent with only review_qa available. Shows the lift
    from adding the other 4 tools beyond what the existing /chat endpoint
    already provides.

Both produce an AgentOutput matching the full agent's shape so the eval
pipeline can treat them uniformly.
"""
import os

import instructor
from groq import Groq
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.agent.nodes.synthesizer import synthesize_node
from backend.agent.prompts import SYNTHESIZER_SYSTEM_PROMPT
from backend.agent.schemas import (
    AgentOutput,
    AgentState,
    AgentTrace,
    Recommendation,
)
from backend.mcp_server.tools import review_qa as review_qa_tool
from backend.mcp_server.tools._loader import supported_asins


def _model() -> str:
    return os.getenv("AGENT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


# ── no_tool baseline ──────────────────────────────────────────────────────────

NO_TOOL_PROMPT = """\
You are ListingLens Copilot. A seller is asking a question about their
Amazon product. You have NO tools available — you must answer from general
knowledge alone. Produce your reasoning plainly; a separate step will
structure it into a Recommendation."""


def run_no_tool(asin: str, query: str) -> AgentOutput:
    """No-tool baseline: single LLM call, no tools, then structured synth."""
    catalog = supported_asins()
    product_name = catalog.get(asin, asin)

    llm = ChatGroq(model=_model(), temperature=0.2, max_tokens=512)
    plain_response = llm.invoke([
        SystemMessage(content=NO_TOOL_PROMPT),
        HumanMessage(content=f"Product: {product_name} (ASIN: {asin})\nQuestion: {query}"),
    ])

    # Synthesize to the Recommendation shape directly via instructor.
    client = instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))
    recommendation = client.chat.completions.create(
        model=_model(),
        response_model=Recommendation,
        max_retries=2,
        messages=[
            {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"NO-TOOL BASELINE — the agent had no tools available.\n\n"
                    f"User question: {query}\n"
                    f"Product: {product_name}\n\n"
                    f"Agent's plain-knowledge response:\n{plain_response.content}\n\n"
                    f"Produce the Recommendation. Confidence should reflect that "
                    f"NO TOOLS were called — typically lower confidence and "
                    f"more 'needs_more_data' decisions."
                ),
            },
        ],
    )

    return AgentOutput(
        asin=asin,
        query=query,
        recommendation=recommendation,
        trace=AgentTrace(tools_called=[], n_tool_calls=0, iterations=0),
    )


# ── single_tool baseline ──────────────────────────────────────────────────────


def _build_single_tool(asin: str) -> list:
    """Build the single-tool tool list — only review_qa, ASIN bound."""
    @tool
    def review_qa(question: str) -> dict:
        """Answer a question about the product's customer reviews. Returns a
        grounded answer with cited review excerpts.
        """
        return review_qa_tool.review_qa(asin=asin, question=question)

    return [review_qa]


SINGLE_TOOL_SYSTEM_PROMPT = """\
You are ListingLens Copilot. You have ONE tool: review_qa, which answers
questions grounded in the product's customer reviews. Use it to gather
evidence, then answer the seller's question in plain prose. A separate
step will structure your answer.

Cap: at most 4 review_qa calls.
"""


def run_single_tool(asin: str, query: str) -> AgentOutput:
    """Single-tool baseline: ReAct agent with only review_qa available."""
    catalog = supported_asins()
    if asin not in catalog:
        raise ValueError(f"ASIN {asin} not in supported catalog")
    product_name = catalog[asin]

    tools = _build_single_tool(asin)
    llm = ChatGroq(model=_model(), temperature=0.1, max_tokens=1024)
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

    def agent_node(state: AgentState) -> dict:
        response = llm_with_tools.invoke(state["messages"])
        new_iters = state.get("iterations", 0)
        new_called = list(state.get("tools_called", []))
        from langchain_core.messages import AIMessage
        if isinstance(response, AIMessage) and response.tool_calls:
            for tc in response.tool_calls:
                new_called.append(tc["name"])
                new_iters += 1
        return {"messages": [response], "iterations": new_iters, "tools_called": new_called}

    def route(state: AgentState):
        from langchain_core.messages import AIMessage
        last = state["messages"][-1]
        if state.get("iterations", 0) >= 4:
            return "synthesizer"
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "synthesizer"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("synthesizer", synthesize_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "synthesizer": "synthesizer"})
    graph.add_edge("tools", "agent")
    graph.add_edge("synthesizer", END)
    compiled = graph.compile()

    initial_state: AgentState = {
        "asin": asin,
        "query": query,
        "product_name": product_name,
        "messages": [
            SystemMessage(content=SINGLE_TOOL_SYSTEM_PROMPT),
            HumanMessage(content=f"Product: {product_name} (ASIN: {asin})\nQuestion: {query}"),
        ],
        "iterations": 0,
        "tools_called": [],
        "plan": [],
        "query_type": "unknown",
        "replans_done": 0,
    }

    final = compiled.invoke(initial_state, config={"recursion_limit": 20})

    return AgentOutput(
        asin=asin,
        query=query,
        recommendation=final["recommendation"],
        trace=AgentTrace(
            tools_called=final.get("tools_called", []),
            n_tool_calls=len(final.get("tools_called", [])),
            iterations=final.get("iterations", 0),
        ),
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────


def run_baseline(baseline: str, asin: str, query: str) -> AgentOutput:
    if baseline == "no_tool":
        return run_no_tool(asin, query)
    if baseline == "single_tool":
        return run_single_tool(asin, query)
    raise ValueError(f"Unknown baseline: {baseline}")
