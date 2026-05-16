"""Shared helpers for loading cached ASIN data from data/processed/."""
import json
import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def asin_features(asin: str) -> dict:
    """Returns the precomputed features dict for an ASIN.

    Raises FileNotFoundError if the ASIN was never analyzed.
    """
    path = PROCESSED_DIR / f"features_{asin}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No cached features for {asin}. "
            f"Expected: {path.relative_to(REPO_ROOT)}"
        )
    with open(path) as f:
        return json.load(f)["features"]


def asin_summary(asin: str) -> dict:
    """Returns the precomputed summary dict for an ASIN (topics, ratings, etc.)."""
    path = PROCESSED_DIR / f"features_{asin}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No cached summary for {asin}. "
            f"Expected: {path.relative_to(REPO_ROOT)}"
        )
    with open(path) as f:
        return json.load(f)["summary"]


def asin_reviews_df(asin: str, limit: int = 100) -> pd.DataFrame:
    """Returns the enriched reviews DataFrame for an ASIN.

    The app's /chat endpoint uses limit=100 by convention — matching that here
    so the agent's RAG sees the same view as the existing chat tool.
    """
    path = PROCESSED_DIR / f"nlp_{asin}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"No cached reviews for {asin}. "
            f"Expected: {path.relative_to(REPO_ROOT)}"
        )
    df = pd.read_csv(path)
    return df.head(limit) if limit else df


def mock_market_data() -> dict:
    """Loads the seeded mock-market data used by competitor/price/trend tools."""
    path = REPO_ROOT / "backend" / "data" / "mock_market_data.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Mock market data missing at {path.relative_to(REPO_ROOT)}"
        )
    with open(path) as f:
        return json.load(f)


def supported_asins() -> dict:
    """Returns the 12-ASIN catalog from src/ingest.py.

    Imports locally so this module stays light when only mock-data tools load.
    """
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from src.ingest import SUPPORTED_ASINS
    return dict(SUPPORTED_ASINS)
