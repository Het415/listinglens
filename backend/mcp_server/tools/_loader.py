"""Shared helpers for loading cached ASIN data from data/processed/."""
import json
import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
DB_PATH = PROCESSED_DIR / "listinglens.duckdb"

# The DuckDB warehouse (scripts/build_duckdb.py) is an optional accelerator.
# When it exists, the three product-data loaders read from it; on ANY problem
# (missing table/row, driver issue) they fall back to the source files — so the
# agent and tools behave identically whether or not the DB has been built.


def _db_query(sql: str, params: list):
    """Run a read-only DuckDB query, or return None if the DB is unavailable."""
    if not DB_PATH.exists():
        return None
    try:
        import duckdb
        con = duckdb.connect(str(DB_PATH), read_only=True)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 — never let the DB break the file path
        print(f"[_loader] DuckDB read failed ({type(e).__name__}: {e}); using files")
        return None


def asin_features(asin: str) -> dict:
    """Returns the precomputed features dict for an ASIN.

    Raises FileNotFoundError if the ASIN was never analyzed.
    """
    rows = _db_query("SELECT features_json FROM product_features WHERE asin = ?", [asin])
    if rows:
        return json.loads(rows[0][0])

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
    rows = _db_query("SELECT summary_json FROM product_summary WHERE asin = ?", [asin])
    if rows:
        return json.loads(rows[0][0])

    path = PROCESSED_DIR / f"features_{asin}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No cached summary for {asin}. "
            f"Expected: {path.relative_to(REPO_ROOT)}"
        )
    with open(path) as f:
        return json.load(f)["summary"]


def stratified_reviews(df: pd.DataFrame, limit: int | None, by: str = "rating") -> pd.DataFrame:
    """Take `limit` rows spread evenly across every value of `by`.

    The source CSVs are sorted by rating, so a plain `.head(limit)` silently
    returns only the lowest ratings — for the 250-row/5-rating catalog,
    `head(100)` is 50x 1-star + 50x 2-star and *zero* 3/4/5-star rows. Any
    vectorstore rebuilt from that view can never answer "what do 5-star
    reviews say?", and every ungrounded answer skews negative.

    Falls back to `.head(limit)` if the `by` column is missing.
    """
    if not limit or len(df) <= limit:
        return df
    if by not in df.columns:
        return df.head(limit)

    groups = df.groupby(by, sort=True)
    per_group = max(1, limit // max(1, groups.ngroups))
    sampled = groups.head(per_group)

    # Integer division can leave the quota short; top up with the rows we
    # have not already taken, preserving the original row order.
    if len(sampled) < limit:
        remainder = df.drop(index=sampled.index).head(limit - len(sampled))
        sampled = pd.concat([sampled, remainder])

    return sampled.sort_index().head(limit)


def asin_reviews_df(asin: str, limit: int = 100) -> pd.DataFrame:
    """Returns the enriched reviews DataFrame for an ASIN.

    The app's /chat endpoint uses limit=100 by convention — matching that here
    so the agent's RAG sees the same view as the existing chat tool. The slice
    is stratified across ratings, not a head() — see stratified_reviews.
    """
    if DB_PATH.exists():
        try:
            import duckdb
            con = duckdb.connect(str(DB_PATH), read_only=True)
            try:
                # EXCLUDE(asin) so the frame matches the source CSV's columns.
                # No SQL LIMIT: we need the full set to stratify, and one ASIN
                # is a few hundred rows.
                sql = "SELECT * EXCLUDE (asin) FROM reviews WHERE asin = ?"
                df = con.execute(sql, [asin]).df()
            finally:
                con.close()
            if not df.empty:
                return stratified_reviews(df, limit)
        except Exception as e:  # noqa: BLE001
            print(f"[_loader] DuckDB reviews read failed ({type(e).__name__}: {e}); using file")

    path = PROCESSED_DIR / f"nlp_{asin}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"No cached reviews for {asin}. "
            f"Expected: {path.relative_to(REPO_ROOT)}"
        )
    df = pd.read_csv(path)
    return stratified_reviews(df, limit)


def mock_market_data() -> dict:
    """Loads the seeded mock-market data used by competitor/price/trend tools."""
    path = REPO_ROOT / "backend" / "data" / "mock_market_data.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Mock market data missing at {path.relative_to(REPO_ROOT)}"
        )
    with open(path) as f:
        return json.load(f)


def asin_conversations(asin: str) -> dict:
    """Full precomputed conversation-analytics payload for an ASIN.

    Written by scripts/precompute_conversations.py. Raises FileNotFoundError
    if conversation analytics were never computed for this ASIN.
    """
    path = PROCESSED_DIR / f"conversations_{asin}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No conversation analytics for {asin}. "
            f"Expected: {path.relative_to(REPO_ROOT)}"
        )
    with open(path) as f:
        return json.load(f)


def asin_conversation_summary(asin: str) -> dict:
    """Lighter conversation-analytics view (drops the full per-conversation list)."""
    full = asin_conversations(asin)
    return {k: v for k, v in full.items() if k != "conversations"}


def supported_asins() -> dict:
    """Returns the 12-ASIN catalog from src/ingest.py.

    Imports locally so this module stays light when only mock-data tools load.
    """
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from src.ingest import SUPPORTED_ASINS
    return dict(SUPPORTED_ASINS)
