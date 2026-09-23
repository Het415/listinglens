import os
import re
import time
import requests
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from src.cancellation import CancelToken, check_cancelled, cancellable_sleep
from src.features import MODEL_FEATURES, rating_sentiment_gap, rating_stats
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

load_dotenv()

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")


os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# No huggingface_hub.login() here. It used to run at import, and importing this
# module is on the production /analyze path (backfill_topic_ids), so every cold
# dashboard load made a blocking `whoami` request with no timeout that raised
# on failure: an HF stall, 429 or revoked token hung or 500'd /analyze for all
# 12 products (audit E-08). Serving never needs an HF identity, and dev ingest
# still authenticates: huggingface_hub and datasets read HF_TOKEN from the
# environment by themselves.

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
                        max_retries: int = 3,
                        cancel: CancelToken | None = None) -> list[dict]:
    """
    Sends each review individually to HuggingFace Inference API.
    The router endpoint doesn't support true batching — sends one at a time.

    This loop is where a cancelled analysis actually stops. It dominates the
    3-5 minute runtime (one HTTP round-trip plus a rate-limit delay per
    review), so checking `cancel` once per iteration bounds the wasted work at
    roughly a single review. Both sleeps below are interruptible too, which
    matters most for the 20s+ 503 backoff.
    """
    results = []

    for i, text in enumerate(texts):
        check_cancelled(cancel)
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
                cancellable_sleep(cancel, wait)

            else:
                print(f"API error {response.status_code} on review {i}")
                results.append([{"label": "neutral", "score": 1.0}])
                break

        # small delay — respect rate limits
        cancellable_sleep(cancel, 0.3)

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
#
# Matched as whole words plus inflections (see _keyword_pattern), not
# substrings. Reviewed 2026-09-23 against the 12 shipped products (audit T-09):
# dropped words whose other senses dominated, measured as the share of
# non-wearable reviews each one matched:
#   "works" 34%, "easy" 30% ("works great", "easy to set up")  -> "easy to use"
#   "quality" 33% ("sound/picture quality" under Build)       -> "build quality"
#   "support" 26% ("supports 4K")                              -> "customer service/support"
#   "last" 20%, "hours" 16% ("last week", "hours on hold")     -> "battery life"
#   "music" 28% (a use, not a sound-quality judgement), "fast" 16% ("fast shipping")
#   "connect", "wifi" moved out of Setup: they are Connectivity's words
#   "remote" moved from Connectivity to Features: it is the device's controller
# The first three keywords of each list are what the dashboard shows.
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Battery Life", ["battery", "charge", "drain", "battery life", "dies", "died", "recharge"]),
    ("Sound Quality", ["sound", "audio", "bass", "volume", "loud", "noise", "treble"]),
    ("Build Quality", ["broke", "broken", "flimsy", "durable", "build quality", "material",
                       "cheaply made", "poorly made", "well made", "sturdy"]),
    ("Setup & Installation", ["setup", "set up", "install", "installation", "pairing", "pair",
                              "configure"]),
    ("Performance & Speed", ["slow", "lag", "freeze", "froze", "crash", "buffer", "loading",
                             "sluggish"]),
    ("Customer Service", ["customer service", "return", "refund", "customer support",
                          "tech support", "replaced", "replacement", "warranty", "defective"]),
    ("Value for Money", ["price", "worth", "expensive", "cheap", "value", "money", "cost",
                         "overpriced"]),
    ("Comfort & Fit", ["comfortable", "uncomfortable", "fit", "ear", "wear", "tight", "loose"]),
    ("Connectivity", ["bluetooth", "wifi", "wi-fi", "connection", "connect", "disconnect",
                      "drops", "signal"]),
    ("Features & Usability", ["feature", "button", "app", "easy to use", "difficult",
                              "interface", "remote", "user friendly"]),
]

_CATEGORY_INDEX_BY_NAME = {name: i for i, (name, _) in enumerate(CATEGORY_KEYWORDS)}


def backfill_topic_ids(summary: dict) -> dict:
    """Fill in `id` on `summary["top_topics"]` entries that are missing one.

    Pre-computed `data/processed/features_<asin>.json` caches written before
    `top_topics` carried an `id` store `"id": null` on every entry. Clients that
    fall back to a single sentinel then treat all ten topics as the same topic.

    Labels come from the fixed CATEGORY_KEYWORDS taxonomy, so the id is
    recoverable by name — no need to re-run the NLP pipeline over cached ASINs.
    These are the same ids as the per-review `topic_id` column, so a filled-in
    summary can be cross-referenced against the review table.

    Idempotent: an existing id is never overwritten, and a label outside the
    taxonomy is left untouched. Mutates and returns `summary`.
    """
    if not isinstance(summary, dict):
        return summary

    topics = summary.get("top_topics")
    if not isinstance(topics, list):
        return summary

    for topic in topics:
        if not isinstance(topic, dict) or topic.get("id") is not None:
            continue
        cat_idx = _CATEGORY_INDEX_BY_NAME.get(topic.get("label"))
        if cat_idx is not None:
            topic["id"] = cat_idx

    return summary


def _word_forms(word: str) -> set[str]:
    """A keyword plus its common inflections, so a word-boundary match still
    finds "batteries", "returned", "apps" and "fitting".

    Deliberately small and rule-based: plurals and verb forms, e-drop
    (charge -> charging), y -> ies (battery -> batteries), and a doubled final
    consonant for short consonant-vowel-consonant words (fit -> fitting,
    lag -> laggy). A form that isn't a real word just never matches.
    """
    forms = {word, word + "s", word + "es", word + "ed", word + "ing", word + "er", word + "ers"}
    if word.endswith("e"):
        forms |= {word + "d", word + "r", word + "rs", word[:-1] + "ing"}
    if len(word) > 2 and word.endswith("y") and word[-2] not in "aeiou":
        forms |= {word[:-1] + "ies", word[:-1] + "ied"}
    if (len(word) in (3, 4) and word[-1] not in "aeiouwxy"
            and word[-2] in "aeiou" and word[-3] not in "aeiou"):
        forms |= {word + word[-1] + suffix for suffix in ("ed", "ing", "er", "y")}
    return forms


def _keyword_pattern(keywords: list[str]) -> re.Pattern:
    """One regex per category, matched on WORD boundaries.

    This used to be `any(kw in text_lower ...)`, a raw substring test: "ear"
    matched "year", "hear" and "near", "app" matched "happy" and "apple", "fit"
    matched "benefit". Every category then covered 55-99% of reviews, so the
    topic and complaint numbers said nothing (audit E-03). A multi-word keyword
    ("set up") matches with any whitespace between its words.
    """
    alternatives: list[str] = []
    for kw in keywords:
        words = kw.split()
        if len(words) > 1:
            alternatives.append(r"\s+".join(re.escape(w) for w in words))
        else:
            alternatives.extend(re.escape(f) for f in _word_forms(kw))
    # Longest first, so an alternation never stops at a shorter prefix.
    alternatives.sort(key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b")


_CATEGORY_PATTERNS: list[re.Pattern] = [_keyword_pattern(kws) for _, kws in CATEGORY_KEYWORDS]


def _review_matches_keywords(text_lower: str, pattern: re.Pattern) -> bool:
    return pattern.search(text_lower) is not None


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
    for pattern in _CATEGORY_PATTERNS:
        mention_sets.append([_review_matches_keywords(t, pattern) for t in texts_lower])

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
    Keyword-based category detection (case-insensitive, whole words; see
    _keyword_pattern).

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
                      raw_distribution: dict | None) -> tuple[pd.DataFrame, dict]:
    """
    Combines sentiment scores + topic assignments into features for XGBoost.

    This is the bridge between NLP outputs and the prediction model.
    Each row = one product's aggregated signal (not per-review). The keys are
    exactly src.features.MODEL_FEATURES; the definitions shared with training
    live in src/features.py.

    Features created:
        - avg_compound_score: mean sentiment across the analysed reviews
        - pct_negative / pct_positive: share of reviews by sentiment label
        - avg_positive_score / avg_negative_score: mean class probabilities
        - rating_avg: the product's REAL mean star rating
        - rating_sentiment_gap: do ratings match sentiment?

    `rating_avg` comes from `raw_distribution`, the star counts ingest captured
    before it balanced the sample to 50 reviews per star. The balanced sample's
    own mean is 3.0 for every product (audit E-01). The sentiment features are
    still computed on that balanced sample, which over-weights 1-2 star reviews;
    see the follow-up noted in audit/IMPLEMENTATION_LOG.md (T-08).
    """
    df = df.copy()
    df["topic_id"] = topics

    # per-review columns, kept in the enriched CSV
    df["review_length"] = df["body"].str.len()
    df["is_negative"] = (df["sentiment_label"] == "negative").astype(int)
    df["is_positive"] = (df["sentiment_label"] == "positive").astype(int)

    if raw_distribution:
        rating_avg, _ = rating_stats(raw_distribution)
    else:
        # Only ad-hoc callers get here: ingest always returns a distribution.
        # Say so loudly, because on a star-balanced sample this is the 3.0 bug.
        print("[features] no raw_star_distribution; rating_avg falls back to the "
              "analysed sample, which is biased if the sample was star-balanced")
        rating_avg = float(df["rating"].mean())

    avg_compound = float(df["compound_score"].mean())
    features = {
        "avg_compound_score":   avg_compound,
        "pct_negative":         float(df["is_negative"].mean()),
        "pct_positive":         float(df["is_positive"].mean()),
        "avg_positive_score":   float(df["positive_score"].mean()),
        "avg_negative_score":   float(df["negative_score"].mean()),
        "rating_avg":           rating_avg,
        "rating_sentiment_gap": rating_sentiment_gap(rating_avg, avg_compound),
    }
    assert tuple(features) == MODEL_FEATURES, "served features drifted from MODEL_FEATURES"

    return df, features


# ── Main Pipeline Function ─────────────────────────────────────────────────────

def run_nlp_pipeline(df: pd.DataFrame, raw_distribution: dict | None = None,
                     cancel: CancelToken | None = None) -> dict:
    """
    Master function — runs full NLP pipeline on a reviews DataFrame.

    Called by app.py with the output of get_reviews().
    Returns everything needed by fusion.py and rag_chatbot.py.

    Args:
        df: clean reviews DataFrame from ingest.py
        cancel: optional CancelToken; when the caller sets it the pipeline
            raises AnalysisCancelled at the next checkpoint instead of
            finishing. Checked per review inside sentiment scoring and again
            between steps.

    Returns dict with:
        df_enriched:  original df + sentiment columns + topic_id
        features:     product-level feature dict for XGBoost
        topic_info:   category labels and keywords for dashboard / features
        summary:      human-readable summary stats (categories + top_topics for UI)
    """
    print(f"\nRunning NLP pipeline on {len(df)} reviews...")

    # ── Step 1: Sentiment ──
    print("\nStep 1/3: Sentiment scoring...")
    raw_sentiment = get_sentiment_batch(df["body"].tolist(), cancel=cancel)
    sentiment_df  = parse_sentiment_results(raw_sentiment)

    # attach sentiment columns to reviews DataFrame
    df_enriched = pd.concat(
        [df.reset_index(drop=True), sentiment_df.reset_index(drop=True)],
        axis=1
    )

    return analyze_scored_reviews(df_enriched, raw_distribution, cancel=cancel)


def analyze_scored_reviews(df_enriched: pd.DataFrame,
                           raw_distribution: dict | None = None,
                           cancel: CancelToken | None = None) -> dict:
    """Everything after sentiment scoring: categories, features and summary.

    Split out of run_nlp_pipeline so scripts/recompute_features.py can rebuild
    the cached features_*.json from the committed nlp_*.csv (which already
    holds the sentiment columns) through exactly this code, instead of
    re-running the HF sentiment model. Same return shape as run_nlp_pipeline.
    """
    df = df_enriched

    # ── Step 2: Category analysis ──
    check_cancelled(cancel)
    print("\nStep 2/3: Category analysis...")
    topics, topic_info, categories = _build_category_outputs(
        df["body"],
        df["rating"],
    )

    # ── Step 3: Feature engineering ──
    check_cancelled(cancel)
    print("\nStep 3/3: Feature engineering...")
    df_enriched, features = engineer_features(df_enriched, topics, raw_distribution)

    # build monthly sentiment timeline from enriched df
    if "timestamp" in df_enriched.columns:
        ts_raw = pd.to_numeric(df_enriched["timestamp"], errors="coerce")
        # HF / APIs may use seconds (~1e9) or milliseconds (~1e12)
        if ts_raw.notna().any() and ts_raw.max() < 1e11:
            df_enriched["timestamp_parsed"] = pd.to_datetime(ts_raw, unit="s", errors="coerce")
        else:
            df_enriched["timestamp_parsed"] = pd.to_datetime(ts_raw, unit="ms", errors="coerce")
    else:
        df_enriched["timestamp_parsed"] = pd.Series(
            [pd.NaT] * len(df_enriched), index=df_enriched.index, dtype="datetime64[ns]"
        )

    timeline_valid = df_enriched.dropna(subset=["timestamp_parsed"])
    if len(timeline_valid) == 0:
        sentiment_timeline: dict = {}
    else:
        monthly = timeline_valid.groupby(
            timeline_valid["timestamp_parsed"].dt.to_period("M")
        )["compound_score"].mean()
        sentiment_timeline = {}
        for period, score in monthly.tail(18).items():
            sentiment_timeline[str(period)] = round(float(score), 3)

    # ── Summary stats for dashboard ──
    summary = {
        "total_reviews":    len(df),
        # The product's real mean, not the balanced sample's 3.0 (audit E-01).
        "avg_rating":       round(features["rating_avg"], 2),
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
        "sentiment_timeline": sentiment_timeline,
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