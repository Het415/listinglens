"""Golden prompts: with no conversation context, every LLM prompt is unchanged.

The eval (eval/run_eval.py) calls `run_agent(asin=..., query=...)` with no
context, and its runs are only comparable with earlier ones if the prompts are
the same bytes. So the exact messages each LLM call builds today are stored in
tests/golden/, and any drift on the no-context path fails here.

How each prompt is captured, all offline (no key, no network):
  - planner and synthesizer: `groq_client` returns a fake instructor client
    whose `chat.completions.create` records its `messages` and returns canned
    structured output. The real `resilient_call` calls it, as in production.
  - executor: ChatGroq is replaced by `_CapturingChatGroq` below,
    and each request is serialised with langchain_groq's own
    `_convert_message_to_dict` — the wire form, not the Python objects.
  - quick path: the real `review_qa` -> `ask_question` -> `SimpleRAGChain`
    over a fake vectorstore and a fake ChatGroq; the captured string is the
    prompt handed to `.invoke`.

The same prompts are checked a second time through POST /assistant/query, so
the endpoint's no-history path is pinned too, not just the library entry.

Regenerating is a deliberate prompt change and breaks eval comparability:
    LISTINGLENS_UPDATE_GOLDEN=1 pytest tests/test_context_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_groq.chat_models import _convert_message_to_dict

from backend.agent import graph
from backend.agent.nodes import executor, planner, synthesizer
from backend.agent.schemas import Plan, Recommendation
from backend.mcp_server.tools import review_qa as review_qa_tool
from src import rag_chatbot

GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.getenv("LISTINGLENS_UPDATE_GOLDEN") == "1"

ASIN = "B08XPWDSWW"
QUERY = "Why are returns spiking on this product?"
RQ_QUESTION = "What do 1-star reviews say?"
QUICK_QUESTION = "What do 1-star reviews say about the battery?"
REVIEW_QA_STUB = {"answer": "Battery complaints dominate.", "sources": [], "n_sources": 0}


class _CapturingChatGroq:
    """Stands in for ChatGroq: records every request, replays a script."""

    def __init__(self, requests: list, script: list):
        self._requests, self._script = requests, script

    def __call__(self, **kwargs):  # the executor calls ChatGroq(model=..., ...)
        return self

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        self._requests.append(list(messages))
        return self._script[min(len(self._requests), len(self._script)) - 1]


def _wire(messages) -> list[str]:
    """Each message as langchain_groq sends it, serialised."""
    return [json.dumps(_convert_message_to_dict(m), sort_keys=True) for m in messages]


def _check(name: str, text: str) -> None:
    path = GOLDEN / name
    if UPDATE:
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"missing golden file {path}; see this module's docstring"
    assert text == path.read_text(encoding="utf-8"), f"{name} drifted from its golden copy"


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class _InstructorRecorder:
    """Stands in for `groq_client()`: records `create` kwargs, returns `result`."""

    def __init__(self, calls: list, result):
        self._calls, self._result = calls, result
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self._calls.append(kwargs)
        return self._result


@pytest.fixture
def captured(monkeypatch):
    """Every agent LLM call faked and recorded; the graph itself is real."""
    calls = {"planner": [], "executor": [], "synthesizer": []}
    plan = Plan(query_type="returns", tool_sequence=["review_qa", "predict_return_risk"],
                rationale="returns question")
    rec = Recommendation(decision="go", confidence=0.8, summary="Low return risk.")
    script = [
        AIMessage(content="", tool_calls=[
            {"name": "review_qa", "args": {"question": RQ_QUESTION}, "id": "call_1"}]),
        AIMessage(content="I have enough evidence."),
    ]
    monkeypatch.setattr(planner, "groq_client",
                        lambda **_: _InstructorRecorder(calls["planner"], plan))
    monkeypatch.setattr(synthesizer, "groq_client",
                        lambda **_: _InstructorRecorder(calls["synthesizer"], rec))
    monkeypatch.setattr(executor, "ChatGroq", _CapturingChatGroq(calls["executor"], script))
    monkeypatch.setattr(review_qa_tool, "review_qa", lambda asin, question: dict(REVIEW_QA_STUB))
    monkeypatch.setattr(graph, "_GRAPH_CACHE", {})
    return calls


def _check_agent_prompts(calls: dict) -> None:
    assert len(calls["planner"]) == 1 and len(calls["synthesizer"]) == 1
    assert len(calls["executor"]) == 2
    _check("planner_messages.json", _dump(calls["planner"][0]["messages"]))
    _check("executor_turn1.json", _dump([json.loads(m) for m in _wire(calls["executor"][0])]))
    _check("executor_turn2.json", _dump([json.loads(m) for m in _wire(calls["executor"][1])]))
    _check("synthesizer_messages.json", _dump(calls["synthesizer"][0]["messages"]))


def test_run_agent_prompts_match_the_golden_copies(captured):
    graph.run_agent(asin=ASIN, query=QUERY)  # exactly how eval/run_eval.py calls it
    _check_agent_prompts(captured)


def test_the_copilot_endpoint_without_history_sends_the_same_prompts(client, captured):
    res = client.post("/assistant/query", json={"asin": ASIN, "query": QUERY, "mode": "copilot"})
    assert res.status_code == 200
    assert "event: recommendation" in res.text and "event: error" not in res.text
    _check_agent_prompts(captured)


# ── quick path ────────────────────────────────────────────────────────────────

class _FakeVectorstore:
    def __init__(self, searches: list):
        self._searches = searches

    def similarity_search(self, query, **kwargs):
        self._searches.append((query, kwargs))
        return [
            Document(page_content="The battery died after two weeks of normal use.",
                     metadata={"rating": 1, "sentiment_label": "negative", "compound_score": -0.6}),
            Document(page_content="Stopped charging entirely, returned it for a refund.",
                     metadata={"rating": 1, "sentiment_label": "negative", "compound_score": -0.4}),
        ]


class _FakeRagLLM:
    """Stands in for langchain_groq.ChatGroq inside build_rag_chain."""

    def __init__(self, prompts: list):
        self._prompts = prompts

    def __call__(self, **kwargs):
        return self

    def invoke(self, prompt_text):
        self._prompts.append(prompt_text)
        return SimpleNamespace(content="Based on the 1-star reviews, the battery fails early.")


@pytest.fixture
def rag(monkeypatch):
    """The real RAG chain over a fake index and LLM, cached as review_qa's chain."""
    import langchain_groq

    captured = {"prompts": [], "searches": []}
    monkeypatch.setattr(langchain_groq, "ChatGroq", _FakeRagLLM(captured["prompts"]))
    chain = rag_chatbot.build_rag_chain(_FakeVectorstore(captured["searches"]))
    monkeypatch.setattr(review_qa_tool, "_CHAIN_CACHE", {ASIN: chain})
    return captured


def _check_quick_prompt(captured: dict) -> None:
    assert captured["searches"] == [
        (QUICK_QUESTION, {"k": 5, "filter": {"rating": 1}, "fetch_k": rag_chatbot.FILTERED_FETCH_K}),
    ]
    assert len(captured["prompts"]) == 1
    _check("rag_prompt.txt", captured["prompts"][0])


def test_review_qa_prompt_matches_the_golden_copy(rag):
    out = review_qa_tool.review_qa(ASIN, QUICK_QUESTION)
    assert out["n_sources"] == 2
    _check_quick_prompt(rag)


def test_the_quick_endpoint_without_history_sends_the_same_prompt(client, rag):
    res = client.post("/assistant/query",
                      json={"asin": ASIN, "query": QUICK_QUESTION, "mode": "quick"})
    assert res.status_code == 200
    assert "event: answer" in res.text and "event: error" not in res.text
    _check_quick_prompt(rag)
