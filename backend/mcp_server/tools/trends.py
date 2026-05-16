"""trend_signal tool — synthetic Google-Trends-style monthly demand index.

Returns category-level demand signal. Accepts either an ASIN (resolved to
category) or a category directly. Helps the agent reason about whether
the seller's category is rising, flat, or contracting.
"""
from datetime import date

from pydantic import BaseModel, Field

from ._loader import mock_market_data


class TrendSignalInput(BaseModel):
    asin: str | None = Field(None, description="ASIN to resolve category from")
    category: str | None = Field(None, description="Category key (overrides asin)")


class TrendSignalOutput(BaseModel):
    category: str
    months: list[str] = Field(..., description="12 months ending in current month, YYYY-MM")
    values: list[int] = Field(..., description="0-100 demand index per month")
    trend_direction: str = Field(..., description="rising | falling | flat")
    yoy_change_pct: float = Field(..., description="Year-over-year change in demand index")
    notes: str = Field(..., description="Brief qualitative interpretation")


def _last_12_months_labels(end: date | None = None) -> list[str]:
    end = end or date.today()
    months: list[str] = []
    year, month = end.year, end.month
    for _ in range(12):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))


def trend_signal(asin: str | None = None, category: str | None = None) -> dict:
    if not asin and not category:
        raise ValueError("Provide either asin or category")

    data = mock_market_data()

    if category is None:
        category = data["asin_to_category"].get(asin)
        if category is None:
            raise ValueError(
                f"ASIN {asin} is not in the supported catalog. "
                f"Known ASINs: {sorted(data['asin_to_category'].keys())}"
            )

    trend = data["category_trends"].get(category)
    if trend is None:
        raise ValueError(
            f"No trend seed for category '{category}'. "
            f"Known categories: {sorted(data['category_trends'].keys())}"
        )

    out = TrendSignalOutput(
        category=category,
        months=_last_12_months_labels(),
        values=trend["trend_12mo_demand_index"],
        trend_direction=trend["trend_direction"],
        yoy_change_pct=trend["yoy_change_pct"],
        notes=trend["notes"],
    )
    return out.model_dump()


TOOL_NAME = "trend_signal"
TOOL_DESCRIPTION = (
    "Get the category-level demand trend (last 12 months) for an Amazon product's "
    "market. Returns a monthly demand index (0-100), trend direction (rising/falling/"
    "flat), year-over-year change, and qualitative notes. Use this when the question "
    "touches market timing — launching a variant, deciding whether to invest in a "
    "category, or understanding why sales might be shifting."
)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="CLI for trend_signal tool")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--asin", help="10-character ASIN")
    g.add_argument("--category", help="Category key (e.g. earbuds_tws)")
    args = parser.parse_args()

    result = trend_signal(asin=args.asin, category=args.category)
    print(json.dumps(result, indent=2))
