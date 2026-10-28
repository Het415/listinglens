"""MCP server exposing the 6 ListingLens Copilot tools over stdio.

The same Python functions are also importable directly from
backend.mcp_server.tools — this server is the protocol-conformant
surface, the imports are the fast-iteration surface.

Run: python -m backend.mcp_server.server
"""
from typing import Any

# mcp 2.x renamed FastMCP to MCPServer; the decorator and run() API are the
# same. Under the old unbounded `mcp>=1.0` pin a fresh install got 2.x and
# this import failed, so the server could not start (audit E-16).
from mcp.server.mcpserver import MCPServer

from .tools import competitor, image_audit, price, return_risk, review_qa, trends

mcp = MCPServer("listinglens-copilot")


@mcp.tool(name=review_qa.TOOL_NAME, description=review_qa.TOOL_DESCRIPTION)
def review_qa_tool(asin: str, question: str) -> dict[str, Any]:
    return review_qa.review_qa(asin=asin, question=question)


@mcp.tool(name=return_risk.TOOL_NAME, description=return_risk.TOOL_DESCRIPTION)
def return_risk_tool(asin: str) -> dict[str, Any]:
    return return_risk.predict_return_risk(asin=asin)


@mcp.tool(name=competitor.TOOL_NAME, description=competitor.TOOL_DESCRIPTION)
def competitor_tool(asin: str, max_results: int = 5) -> dict[str, Any]:
    return competitor.competitor_search(asin=asin, max_results=max_results)


@mcp.tool(name=price.TOOL_NAME, description=price.TOOL_DESCRIPTION)
def price_tool(asin: str, days: int = 90) -> dict[str, Any]:
    return price.price_history(asin=asin, days=days)


@mcp.tool(name=trends.TOOL_NAME, description=trends.TOOL_DESCRIPTION)
def trends_tool(asin: str | None = None, category: str | None = None) -> dict[str, Any]:
    return trends.trend_signal(asin=asin, category=category)


@mcp.tool(name=image_audit.TOOL_NAME, description=image_audit.TOOL_DESCRIPTION)
def image_audit_tool(
    asin: str, image_urls: list[str] | None = None, main_index: int | None = None
) -> dict[str, Any]:
    return image_audit.image_audit(asin=asin, image_urls=image_urls, main_index=main_index)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
