"""Pydantic models for the ListingLens Copilot agent.

The agent's external contract is `Recommendation` — everything else is an
internal shape. AgentState is the LangGraph state passed between nodes.
"""
from typing import Annotated, Literal, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    """A single piece of cited evidence backing the recommendation.

    `tool` is deliberately NOT required on the wire, and a before-validator
    accepts several spellings of it. Reason: Groq validates the model's
    tool-call arguments against this JSON schema *server-side*, and the
    gpt-oss models are inconsistent about this key — across three retries of
    one query they emitted `tool_name`, `tool`, and `source` respectively.
    A schema that demands any single spelling turns that into a hard 400
    (`tool_use_failed`) which burns every retry and loses the whole
    recommendation. Accepting all of them and normalizing is strictly more
    robust than trying to out-prompt the model.

    The Python attribute and the serialized JSON key stay `tool`, so
    eval/judges.py, backend/agent/run.py and the frontend are unaffected.
    """

    model_config = ConfigDict(populate_by_name=True)

    tool: str = Field(
        default="unknown",
        description=(
            "Name of the tool that produced this evidence. Use the key "
            "'tool' exactly."
        ),
    )
    snippet: str = Field(..., description="Short verbatim or paraphrased excerpt from the tool's output")
    relevance: float = Field(..., ge=0.0, le=1.0, description="How relevant this evidence is to the question, 0-1")

    @model_validator(mode="before")
    @classmethod
    def _accept_tool_aliases(cls, data):
        """Map whichever spelling of the tool key the model used onto `tool`."""
        if isinstance(data, dict) and not data.get("tool"):
            for alt in ("tool_name", "source", "tool_used", "name"):
                if data.get(alt):
                    data = {**data, "tool": data[alt]}
                    break
        return data


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
    evidence_gaps: list[str] = Field(
        default_factory=list,
        description=(
            "What evidence is missing that, if present, would change or "
            "strengthen the decision. Forces the model to say what it does "
            "NOT know before committing to a decision — empty list means "
            "the agent is claiming the trajectory was sufficient. For "
            "launch queries, a non-empty list should push the decision to "
            "'needs_more_data'."
        ),
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
    synthesis_degraded: bool  # True when the Recommendation was assembled locally
                              # after the Synthesizer LLM failed, NOT produced by
                              # the model. Deliberately state and not a field on
                              # `Recommendation`: every field added there is one
                              # more thing the model can malform, and malformed
                              # structured output is the failure this flag exists
                              # to report. Also stops the low-confidence re-plan
                              # loop from firing on a degraded result — it carries
                              # confidence 0.0 by design, and re-looping would
                              # spend another Executor pass against the same rate
                              # limits that caused the degrade.


# ── CLI / API shape ───────────────────────────────────────────────────────────

class AgentInput(BaseModel):
    asin: str = Field(..., description="10-character ASIN the agent reasons about")
    query: str = Field(..., description="Seller's natural-language question")


class AgentTrace(BaseModel):
    """Lightweight trace of what the agent did. Useful for the UI."""

    tools_called: list[str] = Field(default_factory=list)
    n_tool_calls: int = 0
    iterations: int = 0
    synthesis_degraded: bool = Field(
        default=False,
        description=(
            "True when the final Recommendation was assembled from tool "
            "results after the Synthesizer LLM failed to return valid "
            "structured output. The answer is real evidence but the "
            "decision/confidence are not model judgements, so the UI must "
            "label it rather than present it as a normal recommendation."
        ),
    )


class AgentOutput(BaseModel):
    """Top-level return shape from running the agent on one query."""

    asin: str
    query: str
    recommendation: Recommendation
    trace: AgentTrace
