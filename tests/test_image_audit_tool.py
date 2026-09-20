"""The image_audit tool: degradation, payload budget, and wiring.

This tool is a thin HTTP client to the `vislens` audit service, so almost
nothing here tests image logic — that is measured in vislens' own suite. What
matters on this side is that a cold, slow, or absent service costs the agent
one finding rather than the whole run, and that the result fits the
synthesizer's budget.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from backend.agent.graph import _build_tools_for_asin
from backend.agent.schemas import Plan, ToolName
from backend.mcp_server.tools import image_audit as tool_mod
from backend.mcp_server.tools.image_audit import image_audit


def _ok_payload() -> dict:
    """A realistic service response, shaped like a measured one."""
    return {
        "rules_version": "v1",
        "audit_id": "abc123def456",
        "n_images": 6,
        "headline": "fail",
        "main_index": 0,
        "f_schema": ["check_code", "status", "measured_value"],
        "key": {"f": "verdict", "a": "measured, not a verdict"},
        "set_checks": [],
        "legend": {
            "occ": {
                "check": "frame_occupancy",
                "rule": "product bounding box ≥85% of the frame",
            }
        },
        "groups": [
            {"i": [0], "n_pass": 4, "f": [["occ", "fail", 0.4577]]},
            {"i": [1, 2, 3, 4, 5], "n_pass": 4, "a": [["wbg", "fail", 0.0045]]},
        ],
        "duplicates": {"method": "dhash", "threshold": 8, "clusters": []},
    }


# ── Degradation: the contract that matters ───────────────────────────────────


def test_unreachable_service_degrades_instead_of_raising(monkeypatch):
    """A cold sidecar must cost one finding, not the run.

    This is a better degradation story than `competitor_search`'s, and it is
    the reason the image code lives behind HTTP: what is lost is an
    enhancement, and the agent still has five working tools.
    """
    def boom(*_a, **_k):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(tool_mod.urllib.request, "urlopen", boom)
    out = image_audit(asin="B08XPWDSWW")

    assert out["status"] == "unavailable"
    assert "unreachable" in out["reason"]
    assert out["audit"] is None


def test_timeout_degrades_and_names_the_budget(monkeypatch):
    def slow(*_a, **_k):
        raise TimeoutError()

    monkeypatch.setattr(tool_mod.urllib.request, "urlopen", slow)
    out = image_audit(asin="B08XPWDSWW")

    assert out["status"] == "unavailable"
    assert "timed out" in out["reason"]


def test_server_error_degrades_with_the_status_code(monkeypatch):
    def five_hundred(*_a, **_k):
        raise urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(tool_mod.urllib.request, "urlopen", five_hundred)
    out = image_audit(asin="B08XPWDSWW")

    assert out["status"] == "unavailable"
    assert "502" in out["reason"]


def test_unexpected_exception_still_degrades(monkeypatch):
    """Belt and braces: no exception type from the transport should escape and
    kill a run that five other tools could have answered."""
    def weird(*_a, **_k):
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr(tool_mod.urllib.request, "urlopen", weird)
    assert image_audit(asin="B08XPWDSWW")["status"] == "unavailable"


def test_blocked_page_is_reported_as_blocked_not_as_an_error(monkeypatch):
    """Amazon refusing a datacenter client is an expected outcome with a
    remedy, not a failure to paper over."""
    monkeypatch.setattr(
        tool_mod,
        "_post",
        lambda *_a, **_k: (
            {
                "status": "blocked",
                "reason": "Amazon served a bot challenge",
                "remedy": "upload the image files instead",
            },
            "",
        ),
    )
    out = image_audit(asin="B08XPWDSWW")

    assert out["status"] == "blocked"
    assert "challenge" in out["reason"]
    assert "upload" in out["audit"]["remedy"]


# ── Happy path and passthrough ───────────────────────────────────────────────


def test_successful_audit_is_passed_through_unreshaped(monkeypatch):
    """Re-shaping the service's payload here would be a second place for the
    verdict semantics to drift out of sync."""
    payload = _ok_payload()
    monkeypatch.setattr(tool_mod, "_post", lambda *_a, **_k: (payload, ""))
    out = image_audit(asin="B08XPWDSWW")

    assert out["status"] == "ok"
    assert out["audit"] == payload
    assert out["audit"]["key"]["a"].startswith("measured")


def test_supplied_urls_are_forwarded_and_asin_is_not(monkeypatch):
    seen: dict = {}

    def capture(path, payload):
        seen.update({"path": path, **payload})
        return _ok_payload(), ""

    monkeypatch.setattr(tool_mod, "_post", capture)
    image_audit(
        asin="B08XPWDSWW",
        image_urls=["https://m.media-amazon.com/images/I/a.jpg"],
        main_index=0,
    )

    assert seen["path"] == "/audit/urls"
    assert seen["image_urls"] == ["https://m.media-amazon.com/images/I/a.jpg"]
    assert seen["main_index"] == 0
    assert "asin" not in seen  # explicit URLs win; no page read is attempted


def test_without_urls_the_asin_drives_a_page_read(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        tool_mod, "_post", lambda path, payload: (seen.update(payload), (_ok_payload(), ""))[1]
    )
    image_audit(asin="B07GZFM1ZM")
    assert seen["asin"] == "B07GZFM1ZM"
    assert "image_urls" not in seen


def test_base_url_and_timeout_are_configurable(monkeypatch):
    monkeypatch.setenv("VISLENS_URL", "http://example.invalid:9999/")
    monkeypatch.setenv("VISLENS_TIMEOUT_S", "2.5")
    assert tool_mod._base_url() == "http://example.invalid:9999"
    assert tool_mod._timeout() == 2.5


def test_a_bad_timeout_env_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("VISLENS_TIMEOUT_S", "not-a-number")
    assert tool_mod._timeout() == tool_mod.DEFAULT_TIMEOUT_S


# ── Payload budget ───────────────────────────────────────────────────────────


def test_result_fits_the_synthesizer_budget(monkeypatch):
    """`synthesizer.py` caps each tool result at 3000 characters, applied per
    ToolMessage. `review_qa` already measures ~2239 against its own cap, and
    this must not be the tool that starts getting truncated."""
    monkeypatch.setattr(tool_mod, "_post", lambda *_a, **_k: (_ok_payload(), ""))
    wire = json.dumps(image_audit(asin="B08XPWDSWW"), separators=(",", ":"))
    assert len(wire) < 2400, f"result is {len(wire)} chars"


def test_degraded_result_is_tiny(monkeypatch):
    monkeypatch.setattr(tool_mod, "_post", lambda *_a, **_k: (None, "service unreachable"))
    wire = json.dumps(image_audit(asin="B08XPWDSWW"), separators=(",", ":"))
    assert len(wire) < 200


# ── Wiring ───────────────────────────────────────────────────────────────────


def test_tool_name_is_in_the_planner_schema():
    """Groq validates `Plan.tool_sequence` against this schema SERVER-SIDE, so
    a planner emitting an unregistered name is a hard 400 that burns every
    retry. The Literal and the tool have to land in the same commit."""
    assert "image_audit" in ToolName.__args__
    plan = Plan(query_type="improve", tool_sequence=["image_audit"], rationale="image question")
    assert plan.tool_sequence == ["image_audit"]


def test_the_agent_binds_six_tools_and_image_audit_takes_no_llm_arguments():
    """The ASIN-scoped convention: the model never supplies identifiers.

    `image_audit` reads its per-request inputs from graph state via
    `InjectedState`, which LangGraph strips from the schema the model sees — so
    it stays zero-argument even though its inputs vary per request.
    """
    tools = _build_tools_for_asin("B08XPWDSWW")
    by_name = {t.name: t for t in tools}

    assert len(tools) == 6
    assert "image_audit" in by_name
    assert list(by_name["image_audit"].args.keys()) == []


def test_image_audit_is_registered_unconditionally():
    """Registering it only when images are attached would reintroduce a real
    bug: `_GRAPH_CACHE` is keyed by ASIN alone, so the first request for an
    ASIN would permanently decide whether the tool exists for every later one.
    """
    from backend.agent import graph as graph_mod

    for asin in ("B08XPWDSWW", "B07GZFM1ZM"):
        names = {t.name for t in graph_mod._build_tools_for_asin(asin)}
        assert "image_audit" in names


def test_planner_prompt_advertises_six_tools_and_the_routing_rule():
    """A prompt that says five while six are bound leaves the planner
    systematically unaware of one."""
    from backend.agent.prompts import PLANNER_SYSTEM_PROMPT as prompt

    assert "6 total" in prompt
    assert "5 total" not in prompt
    assert "image_audit" in prompt
    assert "put image_audit FIRST" in prompt


def test_synthesizer_prompt_forbids_re_deriving_a_rule_verdict():
    """The highest-leverage honesty guard in the integration: if the LLM is
    allowed to restate a computed verdict it will eventually report a different
    one than the rules produced."""
    from backend.agent.prompts import SYNTHESIZER_SYSTEM_PROMPT as prompt

    assert "rule verdict" in prompt
    assert "Never report an `a` finding as a violation." in prompt
    assert "main-image rules" in prompt


def test_no_new_query_type_was_added():
    """`QueryType` drives the synthesizer's per-type rubric and
    `run_eval.py`'s launch-only scoring. A fourth type would mean designing a
    fourth rubric and a fourth baseline on a benchmark affordable about once a
    day, so image questions route under `improve`."""
    from backend.agent.schemas import QueryType

    assert set(QueryType.__args__) == {"launch", "returns", "improve", "unknown"}


# ── Gold set ─────────────────────────────────────────────────────────────────


@pytest.fixture
def gold() -> list[dict]:
    with open("eval/gold_set.jsonl") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_gold_set_has_both_positive_and_negative_image_rows(gold):
    """The negative rows are the cheapest high-signal rows in the set: they
    test that the planner does not over-trigger on the word 'listing', or let
    attached images hijack an unrelated question."""
    image_rows = [r for r in gold if r["id"].startswith("images_")]
    positive = [r for r in image_rows if "image_audit" in r["expected_tools"]]
    negative = [r for r in image_rows if "image_audit" not in r["expected_tools"]]

    assert len(positive) == 4
    assert {r["id"] for r in negative} == {"images_005", "images_006"}
    for row in negative:
        assert "NEGATIVE ROW" in row["notes"]


def test_new_rows_cannot_move_the_headline_metric(gold):
    """`DECISION_SCORED_TYPES` is launch-only. Keeping the new rows out of
    `launch` means they cannot perturb the published decision accuracy, so the
    before/after comparison stays readable."""
    from eval.run_eval import DECISION_SCORED_TYPES

    launch_rows = [r for r in gold if r["query_type"] in DECISION_SCORED_TYPES]
    assert len(launch_rows) == 13  # unchanged by this change
    assert all(not r["id"].startswith("images_") for r in launch_rows)


def test_gold_rows_are_well_formed(gold):
    from backend.agent.schemas import ToolName as TN

    ids = [r["id"] for r in gold]
    assert len(ids) == len(set(ids)), "duplicate gold ids"
    for row in gold:
        assert row["expected_decision"] in ("go", "no_go", "needs_more_data")
        assert row["expected_tools"], f"{row['id']} has no expected tools"
        for name in row["expected_tools"]:
            assert name in TN.__args__, f"{row['id']} names unknown tool {name}"
