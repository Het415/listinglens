"""Structured schema for the executive brief.

A tight, exec-facing shape: a headline, the situation, quantified findings,
risks, and prioritized actions. Mirrors the agent's Recommendation philosophy
(structured, cited, decision-oriented) but framed for a leadership reader.
"""
from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    metric: str = Field(description="The metric or evidence point, e.g. 'Return risk: 62%'.")
    insight: str = Field(description="One sentence on what it means for the business.")


class Action(BaseModel):
    action: str = Field(description="A concrete, owner-actionable recommendation.")
    rationale: str = Field(description="Why this action, tied to the findings.")
    priority: Literal["high", "medium", "low"] = Field(description="Execution priority.")


class ExecutiveBrief(BaseModel):
    headline: str = Field(description="A single punchy sentence a VP would read first.")
    situation: str = Field(description="2-4 sentences framing the current state.")
    key_findings: list[Finding] = Field(description="3-5 quantified findings.")
    top_risks: list[str] = Field(description="2-4 concise risks.")
    recommended_actions: list[Action] = Field(description="3-5 prioritized actions.")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence given the evidence.")
