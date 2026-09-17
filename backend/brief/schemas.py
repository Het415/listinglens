"""Structured schema for the executive brief.

A tight, exec-facing shape: a headline, the situation, quantified findings,
risks, and prioritized actions. Mirrors the agent's Recommendation philosophy
(structured, cited, decision-oriented) but framed for a leadership reader.

Fields the model tends to improvise are deliberately forgiving. Groq validates
tool-call arguments against this JSON schema *server-side*, so a cosmetic
mismatch — `"High"` instead of `"high"`, or folding the rationale into the
action text — becomes a hard 400 that loses the entire brief. Accepting the
model's natural output and normalizing it is strictly more robust than trying
to out-prompt it. See backend/agent/schemas.py:Evidence for the same reasoning.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _hide_default(schema: dict) -> None:
    """Drop `default` from the emitted JSON schema for one field.

    The field stays optional in Python (so a missing value can never 400), but
    the model no longer *sees* a default it can lazily copy. Without this, the
    advertised `"default": "medium"` made the model mark every action medium.
    """
    schema.pop("default", None)


def _first_key(data: dict, *names: str) -> str | None:
    """Return the first non-empty value among `names`."""
    for n in names:
        v = data.get(n)
        if v:
            return v if isinstance(v, str) else str(v)
    return None


class Finding(BaseModel):
    """One quantified finding.

    NOTHING is required on the wire. These models improvise field names inside
    nested objects more than anywhere else — across consecutive runs the same
    prompt produced `metric`/`insight`, then `title`/`detail`. Since Groq
    validates server-side, any required field turns that into a 400 that
    discards the whole brief. Defaults + alias mapping make that impossible,
    and the normalizer below puts the content where the UI expects it.
    """

    model_config = ConfigDict(populate_by_name=True)

    metric: str = Field(default="", description="The metric or evidence point, e.g. 'Return risk: 62%'.")
    insight: str = Field(default="", description="One sentence on what it means for the business.")
    value: str = Field(default="", description="Optional raw value for the metric.")

    @model_validator(mode="before")
    @classmethod
    def _accept_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        d = dict(data)
        d["metric"] = _first_key(d, "metric", "title", "name", "label") or ""
        d["insight"] = _first_key(d, "insight", "detail", "description", "summary") or ""
        d["value"] = _first_key(d, "value", "figure", "number") or ""
        return d


class Action(BaseModel):
    """One prioritized action. Same tolerance rationale as Finding."""

    model_config = ConfigDict(populate_by_name=True)

    action: str = Field(default="", description="A concrete, owner-actionable recommendation.")
    rationale: str = Field(default="", description="Why this action, tied to the findings.")
    priority: Literal["high", "medium", "low"] = Field(
        default="medium",
        description=(
            "Execution priority. Choose deliberately per action — at least one "
            "action should be 'high' and at least one 'low'."
        ),
        json_schema_extra=_hide_default,
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        d = dict(data)
        d["action"] = _first_key(d, "action", "title", "recommendation", "name") or ""
        d["rationale"] = _first_key(d, "rationale", "detail", "description", "why") or ""
        return d

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        """Accept 'High'/'HIGH'/'P1' etc. — the model rarely matches case."""
        if not isinstance(v, str):
            return v
        cleaned = v.strip().lower()
        aliases = {
            "p0": "high", "p1": "high", "urgent": "high", "critical": "high",
            "p2": "medium", "normal": "medium", "moderate": "medium",
            "p3": "low", "minor": "low", "nice-to-have": "low",
        }
        cleaned = aliases.get(cleaned, cleaned)
        return cleaned if cleaned in ("high", "medium", "low") else "medium"


class ExecutiveBrief(BaseModel):
    headline: str = Field(default="", description="A single punchy sentence a VP would read first.")
    situation: str = Field(default="", description="2-4 sentences framing the current state.")
    key_findings: list[Finding] = Field(default_factory=list, description="3-5 quantified findings.")
    top_risks: list[str] = Field(default_factory=list, description="2-4 concise risks.")
    recommended_actions: list[Action] = Field(default_factory=list, description="3-5 prioritized actions.")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="0-1 confidence given the evidence.")
