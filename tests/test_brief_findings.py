"""Every key finding in the executive brief must carry its insight text.

Context: a live brief for B075X8471B rendered findings as bare titles
("Overall sentiment", "Customer Service complaints", ...). The Finding schema
advertised `"default": ""` for `insight`, so the model skipped it, and
explanations under unmapped names (`impact`, ...) or in `value` were dropped.

No network and no API key — these exercise the schema only.
"""

from __future__ import annotations

import pytest
from instructor import openai_schema

from backend.brief.schemas import ExecutiveBrief, Finding


def _wire_finding_schema() -> dict:
    # What instructor actually sends to Groq as the tool's parameters.
    params = openai_schema(ExecutiveBrief).openai_schema["parameters"]
    return params["$defs"]["Finding"]


def test_insight_default_is_hidden_from_the_model():
    insight = _wire_finding_schema()["properties"]["insight"]
    assert "default" not in insight
    assert insight["type"] == "string"


def test_insight_stays_optional_on_the_wire():
    # Groq validates server-side: a required field would turn one omission
    # into a 400 that loses the whole brief.
    assert "insight" not in _wire_finding_schema().get("required", [])


@pytest.mark.parametrize("alias", ["impact", "implication", "explanation"])
def test_new_aliases_map_to_insight(alias):
    f = Finding.model_validate({"metric": "Return risk: 62%", alias: "Returns erode margin."})
    assert f.insight == "Returns erode margin."


def test_value_only_finding_promotes_value_to_insight():
    f = Finding.model_validate({"metric": "Overall sentiment", "value": "41% of reviews read negative."})
    assert f.insight == "41% of reviews read negative."
    assert f.value == "41% of reviews read negative."


def test_explicit_insight_wins_over_value():
    f = Finding.model_validate({"metric": "Avg rating", "insight": "Below category norm.", "value": "3.4"})
    assert f.insight == "Below category norm."
    assert f.value == "3.4"


def test_empty_finding_still_validates():
    f = Finding.model_validate({})
    assert (f.metric, f.insight, f.value) == ("", "", "")


def test_brief_with_mixed_findings_validates():
    brief = ExecutiveBrief.model_validate({
        "key_findings": [
            {"title": "Customer Service complaints", "impact": "Drives 1-star reviews."},
            {"metric": "Overall sentiment", "value": "Mostly positive."},
            {},
        ],
    })
    assert [f.insight for f in brief.key_findings] == [
        "Drives 1-star reviews.", "Mostly positive.", "",
    ]
