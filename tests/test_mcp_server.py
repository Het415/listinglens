"""The MCP server must import and serve the same six tools the agent uses.

`mcp>=1.0` was unbounded, so a fresh install resolved mcp 2.x, where
`mcp.server.fastmcp` no longer exists, and `python -m backend.mcp_server.server`
died on import (audit E-16). Nothing imported the server in CI, so it stayed
broken unseen. This imports it and lists its tools: offline, no LLM.
"""

from __future__ import annotations

import asyncio

from backend.agent.graph import _build_tools_for_asin
from backend.mcp_server import server


def _names() -> set[str]:
    return {t.name for t in asyncio.run(server.mcp.list_tools())}


def test_the_server_imports_and_lists_its_tools():
    assert _names() == {
        "review_qa", "predict_return_risk", "competitor_search",
        "price_history", "trend_signal", "image_audit",
    }


def test_it_serves_the_same_tools_as_the_agent():
    assert _names() == {t.name for t in _build_tools_for_asin("B08XPWDSWW")}
