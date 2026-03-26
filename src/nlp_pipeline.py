import os
import time
import requests
import numpy as np
import pandas as pd
from dotenv import load_dotenv
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

load_dotenv()

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")


os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# set HF token for authenticated downloads
import huggingface_hub
hf_token = os.getenv("HF_TOKEN")
if hf_token:
    huggingface_hub.login(token=hf_token, add_to_git_credential=False)

# ── HuggingFace Inference API setup ───────────────────────────────────────────
# We use the API instead of loading models locally
# This keeps RAM usage near zero on our free Render deployment
# Model: cardiffnlp/twitter-roberta-base-sentiment-latest
# Why this model: trained on social media text, handles informal review language
# better than standard BERT which was trained on Wikipedia/books

SENTIMENT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
HF_API_URL = "https://router.huggingface.co/hf-inference/models/cardiffnlp/twitter-roberta-base-sentiment-latest/pipeline/text-classification"

HEADERS = {
    "Authorization": f"Bearer {HF_API_KEY}",
    "Content-Type": "application/json",
    "x-use-cache": "0",
}

# ── Sentiment Scoring ──────────────────────────────────────────────────────────

def get_sentiment_batch(texts: list[str],
                        batch_size: int = 8,
                        max_retries: int = 3) -> list[dict]:
    """
    Sends each review individually to HuggingFace Inference API.
    The router endpoint doesn't support true batching — sends one at a time.
    """
    results = []

    for i, text in enumerate(texts):
        # truncate to 512 chars — model max token limit
        text = text[:512]

        for attempt in range(max_retries):
            response = requests.post(
                HF_API_URL,
                headers=HEADERS,
                json={"inputs": text},  # single string, not a list
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                # API returns list of label/score dicts for single input
                results.append(result)
                break

            elif response.status_code == 503:
                wait = 20 * (attempt + 1)
                print(f"Model loading, waiting {wait}s...")
                time.sleep(wait)

            else:
                print(f"API error {response.status_code} on review {i}")
                results.append([{"label": "neutral", "score": 1.0}])
                break

        # small delay — respect rate limits
        time.sleep(0.3)

        # progress indicator
        print(f"Sentiment: {i+1}/{len(texts)} reviews processed", end="\r")

    print()
    return results

def parse_sentiment_results(raw_results: list) -> pd.DataFrame:
    """
    Converts raw API response into clean sentiment DataFrame.

    The API returns scores for all 3 labels (positive/neutral/negative).
    We extract all three so downstream models have rich signal.

    Returns DataFrame with columns:
        sentiment_label: dominant sentiment (positive/neutral/negative)
        sentiment_score: confidence of dominant label (0-1)
        positive_score:  probability of positive (0-1)
        neutral_score:   probability of neutral (0-1)
        negative_score:  probability of negative (0-1)
        compound_score:  positive_score - negative_score (-1 to +1)
                         mirrors VADER compound, useful for XGBoost
    """
    rows = []

    for result in raw_results:
        if not result or not isinstance(result, list):
            rows.append({
                "sentiment_label": "neutral",
                "sentiment_score": 0.5,
                "positive_score": 0.33,
                "neutral_score": 0.34,
                "negative_score": 0.33,
                "compound_score": 0.0,
            })
            continue

        # API wraps single input in extra list — unwrap it
        if isinstance(result[0], list):
            result = result[0]

        # now result is [{label: score}, {label: score}, ...]
        scores = {item["label"].lower(): item["score"] for item in result}

        positive  = scores.get("positive", scores.get("pos", 0.33))
        neutral   = scores.get("neutral",  scores.get("neu", 0.34))
        negative  = scores.get("negative", scores.get("neg", 0.33))

        # dominant label = highest scoring
        dominant = max(scores, key=scores.get)

        rows.append({
            "sentiment_label": dominant,
            "sentiment_score": scores[dominant],
            "positive_score":  positive,
            "neutral_score":   neutral,
            "negative_score":  negative,
            "compound_score":  round(positive - negative, 4),
        })

    return pd.DataFrame(rows)


# ── Keyword category analysis ───────────────────────────────────────────────────

# Fixed review themes: first matching category wins per review (order matters for overlaps).
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Battery Life", ["battery", "charge", "charging", "dies", "drain", "last", "hours"]),
    ("Sound Quality", ["sound", "audio", "bass", "volume", "loud", "noise", "music"]),
    ("Build Quality", ["broke", "broken", "cheap", "flimsy", "durable", "quality", "material"]),
    ("Setup & Installation", ["setup", "install", "connect", "pairing", "pair", "wifi", "configure"]),
    ("Performance & Speed", ["slow", "fast", "lag", "freeze", "crash", "buffer", "loading"]),
    ("Customer Service", ["return", "refund", "support", "replaced", "warranty", "defective"]),
    ("Value for Money", ["worth", "expensive", "cheap", "price", "value", "money", "cost"]),
    ("Comfort & Fit", ["comfortable", "uncomfortable", "fit", "ear", "wear", "tight", "loose"]),
    ("Connectivity", ["bluetooth", "wifi", "connection", "disconnect", "drops", "signal", "remote"]),
    ("Features & Usability", ["feature", "button", "app", "easy", "difficult", "interface", "works"]),
]

_CATEGORY_INDEX_BY_NAME = {name: i for i, (name, _) in enumerate(CATEGORY_KEYWORDS)}


def _review_matches_keywords(text_lower: str, keywords: list[str]) -> bool:
    return any(kw in text_lower for kw in keywords)


def _complaint_level(pct_negative: float) -> str:
    if pct_negative > 50:
        return "HIGH"
    if pct_negative > 30:
        return "MEDIUM"
    return "LOW"


def _build_category_outputs(
    texts: pd.Series,
    ratings: pd.Series,
) -> tuple[list[int], dict, list[dict]]:
    """
    Internal: per-review topic ids, full topic_info for features, and the public
    category list (count >= 5, sorted by count desc) for dashboards.
    """
    print("Running category analysis...")

    texts = texts.reset_index(drop=True)
    ratings = ratings.reset_index(drop=True)
    n = len(texts)
    if n == 0:
        return [], {}, []

    texts_lower = [t.lower() if isinstance(t, str) else "" for t in texts]

    mention_sets: list[list[bool]] = []
    for _name, kws in CATEGORY_KEYWORDS:
        mention_sets.append([_review_matches_keywords(t, kws) for t in texts_lower])

    topics: list[int] = []
    for i in range(n):
        tid = -1
        for cat_idx, mentions in enumerate(mention_sets):
            if mentions[i]:
                tid = cat_idx
                break
        topics.append(tid)

    topic_info: dict = {}
    category_rows: list[dict] = []

    for cat_idx, ((label, trigger_keywords), mentions) in enumerate(
        zip(CATEGORY_KEYWORDS, mention_sets)
    ):
        count = int(sum(mentions))
        neg = 0
        pos = 0
        for i, hit in enumerate(mentions):
            if not hit:
                continue
            r = float(ratings.iloc[i]) if not pd.isna(ratings.iloc[i]) else 3.0
            if 1 <= r <= 2:
                neg += 1
            elif 4 <= r <= 5:
                pos += 1

        raw_neg_pct = (neg / count) * 100 if count else 0.0
        raw_pos_pct = (pos / count) * 100 if count else 0.0
        pct_negative = float(round(raw_neg_pct, 1))
        pct_positive = float(round(raw_pos_pct, 1))

        topic_info[cat_idx] = {
            "label": label,
            "keywords": trigger_keywords,
            "count": count,
        }

        if count >= 5:
            category_rows.append({
                "label": label,
                "keywords": trigger_keywords[:3],
                "count": count,
                "pct_negative": pct_negative,
                "pct_positive": pct_positive,
                "complaint_level": _complaint_level(raw_neg_pct),
            })

    category_rows.sort(key=lambda row: row["count"], reverse=True)
    print(f"Category mentions (>=5 in output): {len(category_rows)}")
    return topics, topic_info, category_rows


def run_category_analysis(texts: pd.Series, ratings: pd.Series) -> list[dict]:
    """
    Keyword-based category detection (case-insensitive substring match).

    For each category, counts reviews with at least one trigger keyword and
    computes the share of those mentions from 1–2★ vs 4–5★ reviews (3★ excluded).

    Returns:
        Sorted list (count descending) of dicts with label, keywords (3 strings),
        count, pct_negative, pct_positive, complaint_level — only categories with
        count >= 5.
    """
    _, _, rows = _build_category_outputs(texts, ratings)
    return rows


# ── Feature Engineering ────────────────────────────────────────────────────────

def engineer_features(df: pd.DataFrame, 
                      topics: list[int],
                      topic_info: dict) -> pd.DataFrame:
    """
    Combines sentiment scores + topic assignments into features for XGBoost.

    This is the bridge between NLP outputs and the prediction model.
    Each row = one product's aggregated signal (not per-review).

    Features created:
        - avg_compound_score: mean sentiment across all reviews
        - pct_negative: what % of reviews are negative
        - pct_positive: what % of reviews are positive
        - negative_topic_score: sentiment of reviews in negative topics
        - rating_sentiment_gap: do ratings match sentiment? (signal for fake reviews)
        - review_length_avg: longer reviews = more engaged customers
    """
    df = df.copy()
    df["topic_id"] = topics

    # per-review features
    df["review_length"] = df["body"].str.len()
    df["is_negative"] = (df["sentiment_label"] == "negative").astype(int)
    df["is_positive"] = (df["sentiment_label"] == "positive").astype(int)

    # aggregate to product level
    features = {
        "avg_compound_score":   df["compound_score"].mean(),
        "pct_negative":         df["is_negative"].mean(),
        "pct_positive":         df["is_positive"].mean(),
        "avg_positive_score":   df["positive_score"].mean(),
        "avg_negative_score":   df["negative_score"].mean(),
        "review_length_avg":    df["review_length"].mean(),
        "rating_avg":           df["rating"].mean(),
        "rating_std":           df["rating"].std(),
        # how many reviews give low rating but positive sentiment?
        # high value = product has real issues despite good reviews
        "rating_sentiment_gap": abs(
            df["rating"].mean() / 5 - df["positive_score"].mean()
        ),
        "n_topics":             len(topic_info),
        "pct_outlier_reviews":  (pd.Series(topics) == -1).mean(),
    }

    return df, features


# ── Main Pipeline Function ─────────────────────────────────────────────────────

def run_nlp_pipeline(df: pd.DataFrame, raw_distribution: dict | None = None) -> dict:
    """
    Master function — runs full NLP pipeline on a reviews DataFrame.

    Called by app.py with the output of get_reviews().
    Returns everything needed by fusion.py and rag_chatbot.py.

    Args:
        df: clean reviews DataFrame from ingest.py

    Returns dict with:
        df_enriched:  original df + sentiment columns + topic_id
        features:     product-level feature dict for XGBoost
        topic_info:   category labels and keywords for dashboard / features
        summary:      human-readable summary stats (categories + top_topics for UI)
    """
    print(f"\nRunning NLP pipeline on {len(df)} reviews...")

    # ── Step 1: Sentiment ──
    print("\nStep 1/3: Sentiment scoring...")
    raw_sentiment = get_sentiment_batch(df["body"].tolist())
    sentiment_df  = parse_sentiment_results(raw_sentiment)

    # attach sentiment columns to reviews DataFrame
    df_enriched = pd.concat(
        [df.reset_index(drop=True), sentiment_df.reset_index(drop=True)],
        axis=1
    )

    # ── Step 2: Category analysis ──
    print("\nStep 2/3: Category analysis...")
    topics, topic_info, categories = _build_category_outputs(
        df["body"],
        df["rating"],
    )

    # ── Step 3: Feature engineering ──
    print("\nStep 3/3: Feature engineering...")
    df_enriched, features = engineer_features(df_enriched, topics, topic_info)

    # ── Summary stats for dashboard ──
    summary = {
        "total_reviews":    len(df),
        "avg_rating":       round(df["rating"].mean(), 2),
        "pct_negative":     round(features["pct_negative"] * 100, 1),
        "pct_positive":     round(features["pct_positive"] * 100, 1),
        "categories":       categories,
        # Frontend compatibility: same shape as old top_topics + extra fields
        "top_topics":       [
            {
                "id":              _CATEGORY_INDEX_BY_NAME[cat["label"]],
                "label":           cat["label"],
                "keywords":        cat["keywords"],
                "count":           cat["count"],
                "pct_negative":    cat["pct_negative"],
                "pct_positive":    cat["pct_positive"],
                "complaint_level": cat["complaint_level"],
            }
            for cat in categories[:6]
        ],
        "raw_star_distribution": raw_distribution,
        "sentiment_by_rating": df_enriched.groupby("rating")["compound_score"]
                                          .mean()
                                          .round(3)
                                          .to_dict(),
    }

    print(f"\nNLP pipeline complete.")
    print(f"  Sentiment: {summary['pct_positive']}% positive, "
          f"{summary['pct_negative']}% negative")
    print(f"  Categories (>=5 mentions): {len(categories)}")

    return {
        "df_enriched": df_enriched,
        "features":    features,
        "topic_info":  topic_info,
        "summary":     summary,
    }