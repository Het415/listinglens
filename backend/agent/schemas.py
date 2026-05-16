"""Pydantic models for the ListingLens Copilot agent.

The agent's external contract is `Recommendation` — everything else is an
internal shape. AgentState is the LangGraph state passed between nodes.
"""
from typing import Annotated, Literal, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


QueryType = Literal["launch", "returns", "improve", "unknown"]
ToolName = Literal[
    "review_qa",
    "predict_return_risk",
    "competitor_search",
    "price_history",
    "trend_signal",
]


class Plan(BaseModel):
    """Output of the Planner node — classification + proposed tool sequence."""

    query_type: QueryType = Field(
        ...,
        description=(
            "launch: 'Should I launch X?'. "
            "returns: 'Why are returns spiking?' / churn / dissatisfaction. "
            "improve: 'How do I improve this listing?' / positioning / copy. "
            "unknown: doesn't fit the above."
        ),
    )
    tool_sequence: list[ToolName] = Field(
        ...,
        min_length=1,
        max_length=6,
        description=(
            "The initial tool sequence the executor should run. "
            "Pick 2-4 tools for most queries; 1 tool only for the very narrowest. "
            "Order matters — list the most informative tool first."
        ),
    )
    rationale: str = Field(
        ...,
        description="One sentence explaining why this plan fits the query.",
    )


# ── Final structured output ───────────────────────────────────────────────────

class Evidence(BaseModel):
    """A single piece of cited evidence backing the recommendation."""

    tool: str = Field(..., description="Name of the tool that produced this evidence")
    snippet: str = Field(..., description="Short verbatim or paraphrased excerpt from the tool's output")
    relevance: float = Field(..., ge=0.0, le=1.0, description="How relevant this evidence is to the question, 0-1")


class Recommendation(BaseModel):
    """The agent's final structured answer for one seller query."""

    decision: Literal["go", "no_go", "needs_more_data"] = Field(
        ...,
        description=(
            "go: clear recommendation to proceed. "
            "no_go: clear recommendation to decline. "
            "needs_more_data: insufficient information for a confident call."
        ),
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="How confident the agent is in the decision, 0-1",
    )
    summary: str = Field(
        ...,
        description="2-3 sentence plain-English summary of the recommendation",
    )
    reasoning_steps: list[str] = Field(
        default_factory=list,
        description="Ordered list of the reasoning steps the agent took",
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Cited evidence from tool outputs",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Risks or caveats the seller should know about",
    )
    suggested_next_actions: list[str] = Field(
        default_factory=list,
        description="Concrete next actions the seller could take",
    )


# ── LangGraph state ───────────────────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    """State threaded through the LangGraph nodes.

    `asin` is set once at entry and read by every tool from state, never
    parsed out of the natural-language query. This is the ASIN-scoped UX
    decision in the plan: the user picks a product first, then asks the
    agent freeform questions in that product's context.

    The state grows as the graph progresses: Planner fills query_type and
    plan; Executor appends messages and increments iterations; Synthesizer
    writes recommendation. replans_done caps the low-confidence re-loop.
    """

    asin: str
    query: str
    product_name: str  # resolved from supported_asins at entry
    messages: Annotated[list[AnyMessage], add_messages]
    iterations: int  # tool-call counter (cap = 8)
    query_type: QueryType  # filled by Planner
    plan: list[str]  # remaining tool names to call (mutates as Executor consumes them)
    tools_called: list[str]  # accumulating record of executed tools (for trace + dedup)
    recommendation: Optional["Recommendation"]  # filled by Synthesizer
    replans_done: int  # how many low-confidence re-loops triggered (cap = 1)


# ── CLI / API shape ───────────────────────────────────────────────────────────

class AgentInput(BaseModel):
    asin: str = Field(..., description="10-character ASIN the agent reasons about")
    query: str = Field(..., description="Seller's natural-language question")


class AgentTrace(BaseModel):
    """Lightweight trace of what the agent did. Useful for the UI."""

    tools_called: list[str] = Field(default_factory=list)
    n_tool_calls: int = 0
    iterations: int = 0


class AgentOutput(BaseModel):
    """Top-level return shape from running the agent on one query."""

    asin: str
    query: str
    recommendation: Recommendation
    trace: AgentTrace
