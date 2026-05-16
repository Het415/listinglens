"""LangGraph single-node ReAct agent for ListingLens Copilot (Stage 2).

Graph topology:

    START → agent → [tool_calls?] → tools → agent  ...
                                  └→ END

After END, a synthesizer step (instructor + Groq) converts the trajectory
into a Recommendation. Stage 3 will lift the synthesizer into its own node;
Stage 2 keeps it as a post-loop call so the graph stays minimal.
"""
import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_groq import ChatGroq
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
from .prompts import SYNTHESIZER_SYSTEM_PROMPT, react_system_prompt
from .schemas import (
    AgentOutput,
    AgentState,
    AgentTrace,
    Recommendation,
)

load_dotenv()

MAX_TOOL_ITERATIONS = 8
# AGENT_MODEL is separate from the existing /chat endpoint's GROQ_MODEL.
# Default is Llama 4 Scout: it emits valid JSON tool_calls reliably on Groq.
# llama-3.3-70b-versatile occasionally emits Llama-native <function=name{...}>
# XML on tool-heavy prompts (e.g., launch decisions), failing Groq validation.
# Override via AGENT_MODEL env var if you want a different model.
AGENT_MODEL = os.getenv("AGENT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


# ── Tool wrappers ─────────────────────────────────────────────────────────────
# The MCP-layer functions take `asin` as an explicit arg. For the LangGraph
# agent, ASIN is part of state — not something the LLM should re-supply on
# every call. So we build per-ASIN tool closures at graph-build time.


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


# ── Graph nodes ───────────────────────────────────────────────────────────────


def _make_agent_node(llm_with_tools):
    """Closure-builds the `agent` node, which calls the LLM and returns its message."""

    def agent_node(state: AgentState) -> dict:
        response = llm_with_tools.invoke(state["messages"])
        new_iterations = state.get("iterations", 0)
        if isinstance(response, AIMessage) and response.tool_calls:
            new_iterations += len(response.tool_calls)
        return {"messages": [response], "iterations": new_iterations}

    return agent_node


def _route_after_agent(state: AgentState) -> Literal["tools", "end"]:
    """Conditional edge: continue to tools, or finish."""
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        return "end"
    if not last.tool_calls:
        return "end"
    if state.get("iterations", 0) >= MAX_TOOL_ITERATIONS:
        return "end"
    return "tools"


# ── Graph builder ─────────────────────────────────────────────────────────────


def build_graph(asin: str):
    """Build a compiled LangGraph for a specific ASIN.

    Returns the compiled graph and the list of tool objects (the latter is
    useful for the run.py CLI to extract names for trajectory tracking).
    """
    tools = _build_tools_for_asin(asin)
    llm = ChatGroq(model=AGENT_MODEL, temperature=0.1, max_tokens=1024)
    # parallel_tool_calls=False is the standard Groq+Llama tool-use stabilizer:
    # Llama 3.3 70B sometimes emits the wrong tool-call format when allowed to
    # call multiple tools in parallel. Forcing serial calls keeps it on the
    # JSON tool_calls path Groq's API expects.
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

    graph = StateGraph(AgentState)
    graph.add_node("agent", _make_agent_node(llm_with_tools))
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "agent")

    return graph.compile(), tools


# ── Synthesizer (post-loop structured output) ─────────────────────────────────


def _synthesize_recommendation(
    query: str,
    final_messages: list,
) -> Recommendation:
    """Run instructor + Groq once to convert the trajectory into a Recommendation.

    Stage 3 will lift this into a dedicated Synthesizer node; Stage 2 keeps
    it as a post-loop call so the LangGraph state machine stays simple.
    """
    import instructor
    from groq import Groq

    client = instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))

    # Build a compact transcript of the agent's research, hiding system noise.
    transcript_lines: list[str] = []
    for m in final_messages:
        if isinstance(m, SystemMessage):
            continue
        if isinstance(m, HumanMessage):
            transcript_lines.append(f"USER QUESTION: {m.content}")
        elif isinstance(m, AIMessage):
            if m.tool_calls:
                for tc in m.tool_calls:
                    transcript_lines.append(
                        f"AGENT CALLED: {tc['name']}({tc.get('args', {})})"
                    )
            if m.content:
                transcript_lines.append(f"AGENT THOUGHT/ANSWER: {m.content}")
        elif isinstance(m, ToolMessage):
            content = str(m.content)
            if len(content) > 1500:
                content = content[:1500] + " ...[truncated]"
            transcript_lines.append(f"TOOL RESULT [{m.name}]: {content}")

    transcript = "\n\n".join(transcript_lines)

    return client.chat.completions.create(
        model=AGENT_MODEL,
        response_model=Recommendation,
        max_retries=2,
        messages=[
            {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Original seller question: {query}\n\n"
                    f"--- Agent trajectory ---\n{transcript}\n\n"
                    f"--- End trajectory ---\n\n"
                    f"Produce the structured Recommendation now."
                ),
            },
        ],
    )


# ── Top-level entry ───────────────────────────────────────────────────────────


def run_agent(asin: str, query: str) -> AgentOutput:
    """Run the agent end-to-end for one (asin, query) and return AgentOutput."""
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
        "messages": [
            SystemMessage(content=react_system_prompt(asin, product_name)),
            HumanMessage(content=query),
        ],
        "iterations": 0,
    }

    final_state = compiled.invoke(initial_state)

    # Collect trace
    tools_called: list[str] = []
    for m in final_state["messages"]:
        if isinstance(m, AIMessage) and m.tool_calls:
            tools_called.extend(tc["name"] for tc in m.tool_calls)

    trace = AgentTrace(
        tools_called=tools_called,
        n_tool_calls=len(tools_called),
        iterations=final_state.get("iterations", 0),
    )

    recommendation = _synthesize_recommendation(query, final_state["messages"])

    return AgentOutput(
        asin=asin,
        query=query,
        recommendation=recommendation,
        trace=trace,
    )
