import os
import re
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # loads your .env file so os.getenv() works

# ── Constants ──────────────────────────────────────────────────────────────────

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "real-time-amazon-data.p.rapidapi.com"

# ASINs we have pre-loaded from HuggingFace dataset
# We'll populate this properly in the next step
SUPPORTED_ASINS = {
    "B07GZFM1ZM": "Fire Stick 4K",
    "B075X8471B": "Fire TV Stick with Alexa (Previous Gen)",
    "B01K8B8YA8": "Echo Dot 2nd Generation",
    "B07H65KP63": "Echo Dot 3rd Generation",
    "B0791TX5P5": "Fire TV Stick HD Latest Release",
    "B08XPWDSWW": "TOZO T10 Bluetooth Earbuds",
    "B010BWYDYA": "Fire Tablet 7 inch 16GB",
}

# ── URL Parser ─────────────────────────────────────────────────────────────────

def extract_asin(url_or_asin: str) -> str:
    """
    Accepts either a raw ASIN or a full Amazon URL.
    Returns the 10-character ASIN string.

    Examples:
        "B09X7CRKRX"  → "B09X7CRKRX"
        "https://www.amazon.com/dp/B09X7CRKRX"  → "B09X7CRKRX"
        "https://www.amazon.com/Sony-Headphones/dp/B09X7CRKRX/ref=..."  → "B09X7CRKRX"
    """
    # if it's already a clean ASIN (10 alphanumeric chars), return it directly
    if re.match(r'^[A-Z0-9]{10}$', url_or_asin.strip()):
        return url_or_asin.strip()

    # otherwise try to extract from URL
    match = re.search(r'/dp/([A-Z0-9]{10})', url_or_asin)
    if match:
        return match.group(1)

    raise ValueError(
        f"Could not extract ASIN from input: {url_or_asin}\n"
        f"Expected a 10-character ASIN or an Amazon product URL."
    )


# ── Review Fetchers ────────────────────────────────────────────────────────────

def fetch_reviews_from_rapidapi(asin: str, max_reviews: int = 250) -> pd.DataFrame:
    """
    Fetches live reviews for any ASIN via RapidAPI.
    Use this for live lookups — limited to 100 free requests/month.
    """
    all_reviews = []
    page = 1

    while len(all_reviews) < max_reviews and page <= 5:
        url = "https://real-time-amazon-data.p.rapidapi.com/product-reviews"
        params = {
            "asin": asin,
            "page": str(page),
            "country": "US",
            "sort_by": "TOP_REVIEWS",
            "verified_purchases_only": "false",
        }
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST,
        }

        response = requests.get(url, headers=headers, params=params)

        # if request fails, stop and return what we have
        if response.status_code != 200:
            print(f"RapidAPI error {response.status_code} on page {page}")
            break

        data = response.json()
        reviews = data.get("data", {}).get("reviews", [])

        # no more reviews available
        if not reviews:
            break

        all_reviews.extend(reviews)
        page += 1

    # if no reviews were fetched, return empty DataFrame with correct columns
    if not all_reviews:
        print("No reviews fetched — check your API key and subscription")
        return pd.DataFrame(columns=["title", "body", "rating", "helpful_votes"])

    # convert to DataFrame
    df = pd.DataFrame(all_reviews)
    print(f"Raw columns from API: {df.columns.tolist()}")  # shows us exact column names

    # keep only the columns we need
    df = df.rename(columns={
        "review_title":       "title",
        "review_comment":     "body",
        "review_star_rating": "rating",
        "helpful_vote_statement": "helpful_votes",
    })

    # only keep columns that exist after renaming
    available = [c for c in ["title", "body", "rating", "helpful_votes"] if c in df.columns]
    return df[available].copy()

def fetch_reviews_from_huggingface(asin: str, max_reviews: int = 250) -> pd.DataFrame:
    """
    Fetches reviews from HuggingFace Amazon Reviews 2023 dataset.
    Loads Parquet files directly — no loading script needed.
    """
    from datasets import load_dataset

    print(f"Loading HuggingFace dataset for ASIN {asin}...")
    print("This may take 1-2 minutes on first run (downloading dataset)")

    # load directly as parquet — works with new datasets library
    ds = load_dataset(
        "McAuley-Lab/Amazon-Reviews-2023",
        "raw_review_Electronics",
        split="full",
        trust_remote_code=True,
    )
        
    # convert to pandas and filter to this ASIN
    df = ds.to_pandas()
    df = df[df["parent_asin"] == asin].copy()

    if df.empty:
        raise ValueError(
            f"ASIN {asin} not found in HuggingFace dataset.\n"
            f"Supported ASINs: {list(SUPPORTED_ASINS.keys())}"
        )

    print(f"Found {len(df)} raw reviews for {asin}")

    # rename to standard column names
    df = df.rename(columns={
        "text":  "body",
        "score": "rating",
        "title": "title",
    })

    # keep only what we need
    keep = [c for c in ["title", "body", "rating"] if c in df.columns]
    return df[keep].copy()


# ── Main Entry Point ───────────────────────────────────────────────────────────

def get_reviews(url_or_asin: str, max_reviews: int = 250,
                mode: str = "auto") -> pd.DataFrame:
    """
    Main function the rest of the project calls.

    Args:
        url_or_asin: Amazon URL or raw ASIN string
        max_reviews: how many reviews to fetch (default 250)
        mode: "auto" | "huggingface" | "rapidapi"
              auto = always uses huggingface (rapidapi free tier unreliable)

    Returns:
        Clean DataFrame with columns: title, body, rating, review_id
    """
    asin = extract_asin(url_or_asin)
    print(f"Extracted ASIN: {asin}")

    if mode == "rapidapi":
        # kept as stub — use only for testing specific ASINs
        print("Warning: RapidAPI free tier has data quality issues")
        df = fetch_reviews_from_rapidapi(asin, max_reviews)
    else:
        # huggingface is default — clean, reliable, free
        df = fetch_reviews_from_huggingface(asin, max_reviews)

    df = clean_reviews(df, max_reviews)
    print(f"Done — {len(df)} clean reviews ready")
    return df


# ── Cleaner ────────────────────────────────────────────────────────────────────

def clean_reviews(df: pd.DataFrame, max_reviews: int = 250) -> pd.DataFrame:
    # if empty DataFrame comes in, return it immediately
    if df.empty:
        print("Warning: empty DataFrame passed to clean_reviews")
        return df
    
    """
    Cleans and filters raw review DataFrame.
    Drops noise, balances star ratings, returns production-ready data.
    """
    # 1. drop rows where review body is missing
    df = df.dropna(subset=["body"])

    #  remove duplicate reviews
    df = df.drop_duplicates(subset=["body"]).reset_index(drop=True)

    # 3. drop reviews under 50 characters — "Great product!" adds no signal
    df = df[df["body"].str.len() >= 50]

    # 4. convert rating to integer
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df = df.dropna(subset=["rating"])
    df["rating"] = df["rating"].astype(int)

    # 5. keep only valid ratings (1-5)
    df = df[df["rating"].between(1, 5)]

    # 6. balance across star ratings — 50 reviews per star
    reviews_per_star = max_reviews // 5
    balanced = []
    for star in [1, 2, 3, 4, 5]:
        star_reviews = df[df["rating"] == star].copy()
        # sort by body length descending — longer reviews have more signal
        star_reviews["body_len"] = star_reviews["body"].str.len()
        star_reviews = star_reviews.sort_values("body_len", ascending=False)
        star_reviews = star_reviews.drop(columns=["body_len"])
        sampled = star_reviews.head(min(reviews_per_star, len(star_reviews)))
        balanced.append(sampled)

    df = pd.concat(balanced, ignore_index=True)

    # 7. clean the text — remove HTML tags, extra whitespace
    df["body"] = df["body"].str.replace(r'<[^>]+>', '', regex=True)
    df["body"] = df["body"].str.replace(r'\s+', ' ', regex=True)
    df["body"] = df["body"].str.strip()

    # 8. add a unique review_id for tracking through the pipeline
    df["review_id"] = range(len(df))

    return df.reset_index(drop=True)