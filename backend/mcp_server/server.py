"""MCP server exposing the 5 ListingLens Copilot tools over stdio.

The same Python functions are also importable directly from
backend.mcp_server.tools — this server is the protocol-conformant
surface, the imports are the fast-iteration surface.

Run: python -m backend.mcp_server.server
"""
from typing import Any

from mcp.server.fastmcp import FastMCP

from .tools import competitor, price, return_risk, review_qa, trends

mcp = FastMCP("listinglens-copilot")


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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
