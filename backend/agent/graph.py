"""LangGraph multi-node agent for ListingLens Copilot (Stage 3).

Graph topology:

    START → Planner → Executor → [route_after_executor]
                          ↑           │
                          └─ tools ───┤  (tool call present → run tools, loop back)
                                      │
                                      ▼
                                 Synthesizer → [route_after_synth]
                                      │             │
                                      │             └─ Executor (one re-plan loop)
                                      ▼
                                     END

Compared to Stage 2's single-node ReAct: the Planner runs once up front to
classify the query and propose a tool sequence; the Executor is now strictly
"pick the next tool to run" and consumes the plan; the Synthesizer is a
proper node (not a post-loop function). A bounded re-plan loop kicks in when
the Synthesizer's confidence is below threshold.
"""
import os

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ..mcp_server.tools import (
    competitor as competitor_tool,
    price as price_tool,
    return_risk as return_risk_tool,
    review_qa as review_qa_tool,
    trends as trends_tool,
)
from ..mcp_server.tools._loader import supported_asins
from .nodes.executor import make_executor_node
from .nodes.planner import plan_node
from .nodes.synthesizer import synthesize_node
from .schemas import (
    AgentOutput,
    AgentState,
    AgentTrace,
)

load_dotenv()

MAX_TOOL_ITERATIONS = 8
MAX_REPLANS = 1                       # one extra Executor loop on low confidence
REPLAN_CONFIDENCE_THRESHOLD = 0.5     # below this triggers the re-plan loop


# ── Per-ASIN tool wrappers ────────────────────────────────────────────────────
# Same as Stage 2: bind ASIN at graph-build time so the LLM never has to
# supply it. Each tool here is a thin closure over the Stage-1 MCP tool.


def _build_tools_for_asin(asin: str) -> list:
    @tool
    def review_qa(question: str) -> dict:
        """Answer a question about the product's customer reviews. Returns a
        grounded answer with cited review excerpts. Include a rating in the
        question (e.g., 'what do 1-star reviews say?') to auto-filter retrieval.
        """
        return review_qa_tool.review_qa(asin=asin, question=question)

    @tool
    def predict_return_risk() -> dict:
        """Quantitative return-risk score (HIGH/MEDIUM/LOW + 0-1 probability)
        for the product with a plain-English explanation of the top drivers.
        """
        return return_risk_tool.predict_return_risk(asin=asin)

    @tool
    def competitor_search() -> dict:
        """Find competing products in the same category. Returns up to 5 competitors
        each with title, brand, price_usd, rating, review_count, top_features, top_complaints.
        """
        return competitor_tool.competitor_search(asin=asin, max_results=5)

    @tool
    def price_history() -> dict:
        """90-day price history for the product: daily prices, min/max/avg,
        volatility classification (low/medium/high), and annotated key events.
        """
        return price_tool.price_history(asin=asin, days=90)

    @tool
    def trend_signal() -> dict:
        """12-month category demand trend: monthly demand index, trend direction
        (rising/falling/flat), year-over-year change, and qualitative notes.
        """
        return trends_tool.trend_signal(asin=asin)

    return [review_qa, predict_return_risk, competitor_search, price_history, trend_signal]


# ── Routing edges ─────────────────────────────────────────────────────────────


def _route_after_executor(state: AgentState):
    """After the Executor emits a message, decide where to go next.

    - If the message has tool_calls → run ToolNode (then loop back).
    - If the iteration cap is hit → force Synthesizer.
    - Otherwise (no tool calls) → Synthesizer.
    """
    last = state["messages"][-1]
    if state.get("iterations", 0) >= MAX_TOOL_ITERATIONS:
        return "synthesize"
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "synthesize"


def _route_after_synthesizer(state: AgentState):
    """After the Synthesizer, optionally re-plan if confidence is low.

    Only ever loops back once (replans_done cap). The Synthesizer's
    recommendation is already in state — the re-loop will let the Executor
    gather more evidence, then the Synthesizer overwrites the recommendation
    with a better-grounded one.
    """
    rec = state.get("recommendation")
    if rec is None:
        return "end"
    if state.get("replans_done", 0) >= MAX_REPLANS:
        return "end"
    if rec.confidence < REPLAN_CONFIDENCE_THRESHOLD:
        return "replan"
    return "end"


def _bump_replan_counter(state: AgentState) -> dict:
    """Tiny pass-through node that increments replans_done before re-entering
    the Executor. Keeping it explicit makes the LangSmith trace readable.
    """
    return {"replans_done": state.get("replans_done", 0) + 1}


# ── Graph builder ─────────────────────────────────────────────────────────────


def build_graph(asin: str):
    """Build a compiled multi-node LangGraph for a specific ASIN."""
    tools = _build_tools_for_asin(asin)

    graph = StateGraph(AgentState)
    graph.add_node("planner", plan_node)
    graph.add_node("executor", make_executor_node(tools))
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("synthesizer", synthesize_node)
    graph.add_node("bump_replan", _bump_replan_counter)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_conditional_edges(
        "executor",
        _route_after_executor,
        {"tools": "tools", "synthesize": "synthesizer"},
    )
    graph.add_edge("tools", "executor")
    graph.add_conditional_edges(
        "synthesizer",
        _route_after_synthesizer,
        {"replan": "bump_replan", "end": END},
    )
    graph.add_edge("bump_replan", "executor")

    return graph.compile(), tools


# ── Top-level entry ───────────────────────────────────────────────────────────


def run_agent(asin: str, query: str) -> AgentOutput:
    """Run the multi-node agent end-to-end and return AgentOutput.

    Same external signature as Stage 2 so the CLI and (future) API endpoint
    don't need to change.
    """
    catalog = supported_asins()
    if asin not in catalog:
        raise ValueError(
            f"ASIN {asin} is not in the supported catalog. "
            f"Known: {sorted(catalog.keys())}"
        )
    product_name = catalog[asin]

    compiled, _ = build_graph(asin)

    initial_state: AgentState = {
        "asin": asin,
        "query": query,
        "product_name": product_name,
        "messages": [HumanMessage(content=query)],
        "iterations": 0,
        "tools_called": [],
        "plan": [],
        "replans_done": 0,
    }

    final_state = compiled.invoke(initial_state, config={"recursion_limit": 50})

    recommendation = final_state.get("recommendation")
    if recommendation is None:
        raise RuntimeError("Synthesizer did not produce a Recommendation")

    trace = AgentTrace(
        tools_called=final_state.get("tools_called", []),
        n_tool_calls=len(final_state.get("tools_called", [])),
        iterations=final_state.get("iterations", 0),
    )

    return AgentOutput(
        asin=asin,
        query=query,
        recommendation=recommendation,
        trace=trace,
    )
