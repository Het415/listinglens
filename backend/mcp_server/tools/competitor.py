"""competitor_search tool — returns competing products for an ASIN's category.

Uses seeded mock data in backend/data/mock_market_data.json. Not a real
Amazon scrape — see eval/README.md for the v1 mock policy.
"""
from pydantic import BaseModel, Field

from ._loader import mock_market_data


class CompetitorSearchInput(BaseModel):
    asin: str = Field(..., description="10-character ASIN of the seller's product")
    max_results: int = Field(5, ge=1, le=10, description="Cap on competitors returned")


class Competitor(BaseModel):
    asin: str
    title: str
    brand: str
    price_usd: float
    rating: float
    review_count: int
    top_features: list[str]
    top_complaints: list[str]


class CompetitorSearchOutput(BaseModel):
    asin: str
    category: str
    n_results: int
    competitors: list[Competitor]


def competitor_search(asin: str, max_results: int = 5) -> dict:
    """Returns up to max_results competitors in the same category as the input ASIN."""
    data = mock_market_data()

    category = data["asin_to_category"].get(asin)
    if category is None:
        raise ValueError(
            f"ASIN {asin} is not in the supported catalog. "
            f"Known ASINs: {sorted(data['asin_to_category'].keys())}"
        )

    raw = data["competitors"].get(asin, [])[:max_results]
    competitors = [Competitor(**c) for c in raw]

    out = CompetitorSearchOutput(
        asin=asin,
        category=category,
        n_results=len(competitors),
        competitors=competitors,
    )
    return out.model_dump()


TOOL_NAME = "competitor_search"
TOOL_DESCRIPTION = (
    "Find competing products in the same category as an Amazon ASIN. "
    "Returns each competitor's title, brand, price, rating, review count, "
    "top features, and top complaints. Use this when you need to benchmark "
    "the seller's product against the market — launch decisions, positioning, "
    "or 'how does our product compare to X?' questions."
)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="CLI for competitor_search tool")
    parser.add_argument("asin", help="10-character ASIN")
    parser.add_argument("--max", type=int, default=5, dest="max_results")
    args = parser.parse_args()

    result = competitor_search(args.asin, args.max_results)
    print(json.dumps(result, indent=2))
