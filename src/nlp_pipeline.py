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


# ── Topic Modeling ─────────────────────────────────────────────────────────────

def run_topic_modeling(texts: list[str],
                       n_topics: int = 8) -> tuple[list[int], dict]:
    """
    Runs topic modeling using KeyBERT-style approach.
    Uses single-process execution to avoid Mac/Python 3.13 segfault.
    """
    from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS
    from sklearn.decomposition import LatentDirichletAllocation
    import numpy as np

    print("Running topic modeling...")

    custom_review_stopwords = [
        "amazon", "product", "just", "like", "get", "got", "use", "used", "using",
        "one", "would", "really", "also", "time", "new", "item", "buy", "bought",
        "purchase", "purchased", "price", "good", "great", "nice", "well", "works",
        "work", "make", "made", "need", "even", "still", "back", "day", "days",
        "month", "months", "year", "first", "second", "came", "come", "know",
        "think", "way", "thing", "things", "little", "lot", "much", "many",
        "better", "best", "worst", "bad", "old", "app", "device", "customer",
        "service", "review", "star", "stars", "highly", "recommend",
    ]
    all_stopwords = sorted(set(ENGLISH_STOP_WORDS).union(custom_review_stopwords))

    # use LDA instead of BERTopic — more stable on Mac/Python 3.13
    # still gives meaningful topics for our use case
    vectorizer = CountVectorizer(
        max_features=1000,
        stop_words=all_stopwords,
        min_df=3,
        ngram_range=(1, 2),  # captures "battery life", "sound quality"
    )

    try:
        X = vectorizer.fit_transform(texts)
    except ValueError:
        # not enough text — return empty topics
        print("Not enough text for topic modeling")
        return [-1] * len(texts), {}

    # fit LDA
    lda = LatentDirichletAllocation(
        n_components=min(n_topics, len(texts) // 2),
        random_state=42,
        max_iter=10,
    )
    lda.fit(X)

    # assign each review to its dominant topic
    doc_topics = lda.transform(X)
    topics = doc_topics.argmax(axis=1).tolist()

    # extract top keywords per topic
    feature_names = vectorizer.get_feature_names_out()
    topic_info = {}

    for topic_id in range(lda.n_components):
        top_indices = lda.components_[topic_id].argsort()[-5:][::-1]
        keywords = [feature_names[i] for i in top_indices]
        label = " · ".join(keywords[:3])
        topic_info[topic_id] = {
            "label": label,
            "keywords": keywords,
            "count": topics.count(topic_id),
        }

    print(f"Found {len(topic_info)} topics")
    return topics, topic_info


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
        topic_info:   topic labels and keywords for dashboard display
        summary:      human-readable summary stats
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

    # ── Step 2: Topic modeling ──
    print("\nStep 2/3: Topic modeling...")
    topics, topic_info = run_topic_modeling(df["body"].tolist())

    # ── Step 3: Feature engineering ──
    print("\nStep 3/3: Feature engineering...")
    df_enriched, features = engineer_features(df_enriched, topics, topic_info)

    # ── Summary stats for dashboard ──
    summary = {
        "total_reviews":    len(df),
        "avg_rating":       round(df["rating"].mean(), 2),
        "pct_negative":     round(features["pct_negative"] * 100, 1),
        "pct_positive":     round(features["pct_positive"] * 100, 1),
        "top_topics":       [
            {
                "id":       tid,
                "label":    info["label"],
                "keywords": info["keywords"],
                "count":    info["count"],
            }
            for tid, info in sorted(
                topic_info.items(),
                key=lambda x: x[1]["count"],
                reverse=True
            )[:6]  # top 6 topics for dashboard
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
    print(f"  Topics found: {len(topic_info)}")

    return {
        "df_enriched": df_enriched,
        "features":    features,
        "topic_info":  topic_info,
        "summary":     summary,
    }