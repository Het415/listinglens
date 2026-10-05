"""The Executor recovers malformed tool calls instead of resending the same turn.

Every executor_degraded row in the evals from 2026-09-23 to 10-02 was a
malformed-tool-call episode that three IDENTICAL attempts could not get past:
the failure is sticky (the 2nd attempt recovered 4 of 13, the 3rd 1 of 9).
Reproduced live on 2026-10-03 on the eval's launch_006 state, where
gpt-oss-safeguard-20b (the executor's fallback) wrote, 2 of 3 times:

    {"name": "price_history", "arguments": {""}"}

price_history takes no arguments, so that call is unambiguous. These tests pin
that it is rebuilt with no extra LLM call, that nothing ambiguous is rebuilt,
and that a retry carries a correction instead of repeating the failed turn.
"""

from __future__ import annotations

import groq
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from backend.agent.graph import _build_tools_for_asin
from backend.agent.nodes import executor as ex

TOOLS = _build_tools_for_asin("B08XPWDSWW")
_REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")

PROBED = '{"name": "price_history", "arguments": {""}"}'   # verbatim, 2026-10-03


def tool_use_failed(generation: str, message: str = "Failed to parse tool call arguments as JSON"):
    """A 400 exactly as the groq SDK raises it (langchain_groq doesn't wrap it)."""
    body = {"error": {"message": message, "type": "invalid_request_error",
                      "code": "tool_use_failed", "failed_generation": generation}}
    return groq.BadRequestError(f"Error code: 400 - {body}",
                                response=httpx.Response(400, request=_REQ), body=body)


# ── reading the rejected generation ──────────────────────────────────────────

def test_reads_the_generation_from_the_sdk_body():
    assert ex._failed_generation(tool_use_failed(PROBED)) == (
        "Failed to parse tool call arguments as JSON", PROBED)


def test_reads_it_from_the_message_when_body_is_gone():
    e = tool_use_failed(PROBED)
    assert ex._failed_generation(RuntimeError(str(e))) == (
        "Failed to parse tool call arguments as JSON", PROBED)


@pytest.mark.parametrize("err", [
    RuntimeError("Error code: 429 - {'error': {'code': 'rate_limit_exceeded'}}"),
    RuntimeError("something unrelated"),
    tool_use_failed(""),
])
def test_anything_else_has_no_generation(err):
    assert ex._failed_generation(err) is None


# ── what may be rebuilt ──────────────────────────────────────────────────────

def test_the_real_tool_set_is_mostly_zero_argument():
    """The premise: only review_qa takes an argument from the model."""
    takes_args = {t.name: ex._model_args(t) for t in TOOLS if ex._model_args(t)}
    assert takes_args == {"review_qa": {"question"}}
    assert len(TOOLS) == 6   # image_audit's injected state is not model-visible


@pytest.mark.parametrize("gen,name", [
    (PROBED, "price_history"),
    ('{"name": "functions.trend_signal", "arguments": {""}"}', "trend_signal"),
    ('{"name": "competitor_search", "arguments": {"asin": "B08XPWDSWW"}}', "competitor_search"),
    ('{"name": "image_audit", "arguments": "}', "image_audit"),
])
def test_a_zero_argument_tool_is_rebuilt_with_no_arguments(gen, name):
    msg = ex._salvage(tool_use_failed(gen), TOOLS, tools_called=["review_qa"])

    assert isinstance(msg, AIMessage)
    assert [(c["name"], c["args"]) for c in msg.tool_calls] == [(name, {})]
    assert msg.tool_calls[0]["id"]
    assert msg.additional_kwargs["salvaged_tool_call"] == gen


def test_review_qa_is_rebuilt_only_from_arguments_that_parse_and_validate():
    ok = '{"name": "review_qa", "arguments": {"question": "What do 1-star reviews say?"}}'
    encoded = '{"name": "review_qa", "arguments": "{\\"question\\": \\"Battery?\\"}"}'
    assert ex._salvage(tool_use_failed(ok), TOOLS, [])
    assert ex._salvage(tool_use_failed(ok), TOOLS, []).tool_calls[0]["args"] == {
        "question": "What do 1-star reviews say?"}
    assert ex._salvage(tool_use_failed(encoded), TOOLS, []).tool_calls[0]["args"] == {"question": "Battery?"}


@pytest.mark.parametrize("gen", [
    # the escaped-quote slip the synthesizer logs show, on a free-text argument
    '{"name": "review_qa", "arguments": {"question": \\"What about battery?\\"}}',
    '{"name": "review_qa", "arguments": {}}',                      # required question missing
    '{"name": "review_qa", "arguments": {"question": 7}}',          # wrong type
    '{"name": "browser.search", "arguments": {"query": "x"}}',      # not a bound tool
    '<tool_call><function=price_history></function></tool_call>',   # qwen's XML syntax
    'I will now call price_history.',
])
def test_nothing_ambiguous_is_rebuilt(gen):
    assert ex._salvage(tool_use_failed(gen), TOOLS, []) is None


def test_a_zero_argument_tool_already_called_is_not_rebuilt():
    """Its result would be identical, and the prompt forbids the repeat."""
    assert ex._salvage(tool_use_failed(PROBED), TOOLS, ["price_history"]) is None


def test_the_rebuilt_call_runs_through_the_graphs_tool_node():
    @tool
    def price_history() -> dict:
        """stub"""
        return {"current_price": 49.99}

    msg = ex._salvage(tool_use_failed(PROBED), [price_history], [])
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([price_history]))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    out = g.compile().invoke({"messages": [msg]})["messages"][-1]

    assert isinstance(out, ToolMessage)
    assert out.tool_call_id == msg.tool_calls[0]["id"]
    assert "49.99" in out.content


# ── the retry loop ───────────────────────────────────────────────────────────

class Scripted:
    """A tools-bound model that answers each invoke from a script."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


BASE = [SystemMessage(content="sys"), HumanMessage(content="Should I launch X?")]
DONE = AIMessage(content="Enough evidence; handing over.")


def test_the_probed_failure_costs_no_second_call():
    llm = Scripted(tool_use_failed(PROBED))
    msg = ex._invoke_with_retry(lambda m: llm, BASE, TOOLS, ["trend_signal", "competitor_search"])

    assert len(llm.calls) == 1
    assert msg.tool_calls[0]["name"] == "price_history"
    assert msg.name != "executor_degraded"


def test_a_retry_carries_a_correction_instead_of_repeating_the_turn():
    bad = tool_use_failed('{"name": "browser.search", "arguments": {"query": "x"}}',
                          "Tool call validation failed: attempted to call tool 'browser.search' "
                          "which was not in request.tools")
    llm = Scripted(bad, DONE)
    msg = ex._invoke_with_retry(lambda m: llm, BASE, TOOLS, [])

    assert msg is DONE
    first, second = llm.calls
    assert first == BASE                       # the turn itself is unchanged
    assert second[:-1] == BASE                 # ...and the retry only appends
    note = second[-1]
    assert isinstance(note, HumanMessage)
    assert "browser.search" in note.content    # says what Groq rejected
    for t in TOOLS:
        assert t.name in note.content          # lists what is valid
    assert "review_qa(question)" in note.content
    assert "plain-text summary" in note.content


def test_an_unrecoverable_turn_still_degrades_on_the_first_model_only():
    """Real resilient_call: _MalformedToolCalls still opts out of failover."""
    gen = '{"name": "review_qa", "arguments": {"question": \\"x\\"}}'
    tried = []

    def bind_for(model):
        tried.append(model)
        return Scripted(tool_use_failed(gen))

    msg = ex._invoke_with_retry(bind_for, BASE, TOOLS, [])

    assert msg.name == "executor_degraded"
    assert not msg.tool_calls
    assert len(tried) == ex.TOOL_CALL_RETRIES and len(set(tried)) == 1
    assert "tool_use_failed" in msg.additional_kwargs["tool_call_error"]


def test_the_node_counts_a_rebuilt_call_like_any_other(monkeypatch):
    class FakeChatGroq:
        def __init__(self, **kwargs):
            pass

        def bind_tools(self, tools, **kwargs):
            return Scripted(tool_use_failed(PROBED))

    monkeypatch.setattr(ex, "ChatGroq", FakeChatGroq)
    update = ex.make_executor_node(TOOLS)({
        "asin": "B08XPWDSWW", "product_name": "TOZO",
        "plan": ["review_qa", "price_history"], "tools_called": ["trend_signal", "competitor_search"],
        "messages": [HumanMessage(content="q")], "replans_done": 0, "iterations": 2,
    })

    assert update["tools_called"][-1] == "price_history"
    assert update["plan"] == ["review_qa"]
    assert update["iterations"] == 3
    assert "executor_degraded" not in update
