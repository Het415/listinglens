"""price_history tool — synthetic Keepa-style price curve for an ASIN.

Generates a daily price series from seeded min/max/avg + key events. Pure
deterministic synthesis from the seed — same ASIN produces the same curve
every call, important for repeatable agent traces.
"""
import math

from pydantic import BaseModel, Field

from ._loader import mock_market_data


class PriceHistoryInput(BaseModel):
    asin: str = Field(..., description="10-character ASIN")
    days: int = Field(90, ge=7, le=180, description="Days of history to return")


class PriceEvent(BaseModel):
    day_offset: int = Field(..., description="Days before today (negative)")
    event: str


class PriceHistoryOutput(BaseModel):
    asin: str
    days: int
    current_price: float
    min_price_90d: float
    max_price_90d: float
    avg_price_90d: float
    current_vs_min_pct: float = Field(..., description="(current-min)/min * 100")
    volatility: str
    daily_prices: list[float] = Field(..., description="Oldest first, newest last")
    key_events: list[PriceEvent]


def _synthesize_curve(seed: dict, days: int) -> list[float]:
    """Builds a price curve from the seed's min/max/avg/events.

    Strategy: start from avg, walk back from today with small sinusoidal noise
    (keeps it deterministic), and inject dips at any `key_events` offsets that
    fall inside the window. No randomness — same inputs -> same output.
    """
    current = seed["current_price"]
    avg = seed["avg_price_90d"]
    pmin = seed["min_price_90d"]
    pmax = seed["max_price_90d"]
    band = max(pmax - pmin, 0.5)

    prices: list[float] = []
    for offset in range(days, 0, -1):
        # gentle sinusoidal wobble around avg, scaled to half the band
        wobble = math.sin(offset / 7.0) * band * 0.15
        p = avg + wobble
        prices.append(round(p, 2))

    # final day is `today` -> current price
    prices.append(round(current, 2))

    # apply event dips
    for ev in seed.get("key_events", []):
        idx = days + ev["day_offset"]
        if 0 <= idx < len(prices):
            evt = ev["event"].lower()
            if "low" in evt or "dip" in evt or "deal" in evt or "discount" in evt or "$" in evt:
                prices[idx] = round(max(pmin, prices[idx] - band * 0.5), 2)

    # clamp to seed band
    return [max(pmin, min(pmax, p)) for p in prices]


def price_history(asin: str, days: int = 90) -> dict:
    data = mock_market_data()

    seed = data["prices"].get(asin)
    if seed is None:
        raise ValueError(
            f"No price seed for ASIN {asin}. "
            f"Known ASINs: {sorted(data['prices'].keys())}"
        )

    daily = _synthesize_curve(seed, days)
    current = daily[-1]
    pmin = seed["min_price_90d"]
    current_vs_min = round(((current - pmin) / pmin) * 100, 1) if pmin > 0 else 0.0

    events = [PriceEvent(**e) for e in seed.get("key_events", [])]

    out = PriceHistoryOutput(
        asin=asin,
        days=days,
        current_price=current,
        min_price_90d=pmin,
        max_price_90d=seed["max_price_90d"],
        avg_price_90d=seed["avg_price_90d"],
        current_vs_min_pct=current_vs_min,
        volatility=seed["volatility"],
        daily_prices=daily,
        key_events=events,
    )
    return out.model_dump()


TOOL_NAME = "price_history"
TOOL_DESCRIPTION = (
    "Get the 90-day price history for an Amazon ASIN. Returns daily prices, "
    "min/max/avg, volatility classification (low/medium/high), and annotated key "
    "events (sales, dips, discontinuation rumors). Use this when the question "
    "touches pricing strategy, deals, or price elasticity — 'should I lower the "
    "price?', 'is my SKU's price stable?', 'when was the last promotional dip?'."
)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="CLI for price_history tool")
    parser.add_argument("asin", help="10-character ASIN")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--summary", action="store_true",
                        help="Skip daily_prices array, show summary only")
    args = parser.parse_args()

    result = price_history(args.asin, args.days)
    if args.summary:
        result["daily_prices"] = f"[{args.days} daily prices omitted]"
    print(json.dumps(result, indent=2))
