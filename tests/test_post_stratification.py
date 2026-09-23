"""Sentiment aggregates describe the product's real reviews, not the sample.

ingest keeps up to 50 reviews per star, so 40% of every sample is 1-2 star by
construction. Averaged as-is, that sample said B08XPWDSWW's reviews were "31%
negative" (13.6% of its real ratings are 1-2 star), and put a sample-biased
compound sentiment beside its real 4.26-star rating, so "significant gap
between ratings and review sentiment" fired on 12/12 products.

The aggregates are now post-stratified: computed per star on the sample, then
weighted by `raw_star_distribution` (src/features.py). Expected values below
are worked by hand.
"""

from __future__ import annotations

import glob
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd
import pytest

import src.fusion as fusion
import src.nlp_pipeline as nlp
from src.features import (
    post_stratified_mean,
    post_stratified_share,
    rating_sentiment_gap,
    rating_stats,
    star_weights,
)

ROOT = Path(__file__).resolve().parent.parent
FEATURE_FILES = sorted(glob.glob(str(ROOT / "data" / "processed" / "features_*.json")))

# A real mix that is 75% 5-star, as the shipped products roughly are.
RAW = {"1": 10, "2": 10, "3": 20, "4": 60, "5": 300}
WEIGHTS = {1: 0.025, 2: 0.025, 3: 0.05, 4: 0.15, 5: 0.75}


# ── the helpers ───────────────────────────────────────────────────────────────

def test_star_weights_are_the_real_shares():
    assert star_weights(RAW, [1, 2, 3, 4, 5]) == pytest.approx(WEIGHTS)


def test_star_weights_renormalise_over_the_sampled_stars():
    assert star_weights(RAW, [4, 5]) == pytest.approx({4: 60 / 360, 5: 300 / 360})


def test_star_weights_refuse_nothing_to_weight():
    with pytest.raises(ValueError):
        star_weights({"1": 0, "5": 0}, [1, 5])


def test_post_stratified_mean_weights_each_star_by_its_real_share():
    per_star = {1: -0.4, 2: -0.2, 3: 0.1, 4: 0.3, 5: 0.5}
    expected = 0.025 * -0.4 + 0.025 * -0.2 + 0.05 * 0.1 + 0.15 * 0.3 + 0.75 * 0.5
    assert post_stratified_mean(per_star, RAW) == pytest.approx(expected)
    assert post_stratified_mean(per_star, RAW) == pytest.approx(0.41)


def test_post_stratified_share_is_the_in_star_part_of_the_real_prevalence():
    # Rates of some property per star: mass = weight x rate.
    rates = {1: 1.0, 2: 0.5, 3: 0.0, 4: 0.5, 5: 0.5}
    # masses 0.025, 0.0125, 0, 0.075, 0.375 -> total 0.4875
    assert post_stratified_share(rates, RAW, (1, 2)) == pytest.approx(0.0375 / 0.4875)
    assert post_stratified_share(rates, RAW, (4, 5)) == pytest.approx(0.45 / 0.4875)
    assert post_stratified_share({s: 0.0 for s in rates}, RAW, (1, 2)) == 0.0


# ── engineer_features ─────────────────────────────────────────────────────────

def _labelled_sample() -> pd.DataFrame:
    """Four reviews per star, star-balanced like ingest's sample, with the
    sentiment labels mixed within each star so the result is not just the
    1-2 star share."""
    labels = {
        1: ["negative", "negative", "negative", "neutral"],   # 0.75 negative
        2: ["negative", "negative", "neutral", "positive"],   # 0.50
        3: ["negative", "neutral", "neutral", "positive"],    # 0.25
        4: ["neutral", "positive", "positive", "positive"],   # 0.00
        5: ["negative", "positive", "positive", "positive"],  # 0.25
    }
    rows = []
    for star, star_labels in labels.items():
        for label in star_labels:
            compound = {"negative": -0.6, "neutral": 0.0, "positive": 0.7}[label]
            rows.append({
                "body": f"a {star}-star review", "rating": star,
                "sentiment_label": label, "compound_score": compound,
                "positive_score": max(compound, 0.0), "negative_score": max(-compound, 0.0),
            })
    return pd.DataFrame(rows)


def test_pct_negative_is_the_weighted_per_star_value():
    df = _labelled_sample()
    _, features = nlp.engineer_features(df, [-1] * len(df), RAW)

    per_star = (df["sentiment_label"] == "negative").groupby(df["rating"]).mean()
    weighted = sum(WEIGHTS[star] * share for star, share in per_star.items())
    assert features["pct_negative"] == pytest.approx(weighted)
    # 0.025*0.75 + 0.025*0.5 + 0.05*0.25 + 0.15*0 + 0.75*0.25
    assert features["pct_negative"] == pytest.approx(0.23125)
    # The plain sample mean, which is what used to be served.
    assert (df["sentiment_label"] == "negative").mean() == pytest.approx(0.35)


def test_every_sentiment_feature_is_post_stratified():
    df = _labelled_sample()
    _, features = nlp.engineer_features(df, [-1] * len(df), RAW)
    for name, column in [("avg_compound_score", "compound_score"),
                         ("avg_positive_score", "positive_score"),
                         ("avg_negative_score", "negative_score")]:
        per_star = df.groupby("rating")[column].mean()
        assert features[name] == pytest.approx(
            sum(WEIGHTS[s] * m for s, m in per_star.items())), name
    positive = (df["sentiment_label"] == "positive").groupby(df["rating"]).mean()
    assert features["pct_positive"] == pytest.approx(
        sum(WEIGHTS[s] * m for s, m in positive.items()))


def test_without_a_distribution_it_falls_back_to_the_sample_loudly():
    df = _labelled_sample()
    out = io.StringIO()
    with redirect_stdout(out):
        _, features = nlp.engineer_features(df, [-1] * len(df), None)
    assert features["pct_negative"] == pytest.approx(0.35)
    assert "no raw_star_distribution" in out.getvalue()


def test_a_product_whose_sentiment_matches_its_stars_has_no_gap():
    """Each review's compound is exactly what the gap formula says its star
    implies (star/5 - 0.5), so there is no gap to report."""
    rows = [{"body": "x", "rating": s, "sentiment_label": "neutral",
             "compound_score": s / 5 - 0.5, "positive_score": 0.5, "negative_score": 0.2}
            for s in range(1, 6) for _ in range(50)]
    df = pd.DataFrame(rows)
    _, features = nlp.engineer_features(df, [-1] * len(df), RAW)

    assert features["rating_sentiment_gap"] < 0.10
    assert features["rating_sentiment_gap"] == pytest.approx(0.0, abs=1e-12)
    explanation = fusion._generate_risk_explanation(features, 0.0)
    assert "significant gap" not in explanation

    # What the old code served: the real rating beside the SAMPLE's compound.
    # The balanced sample's compound is 0.1 (its mean star is 3); the real mean
    # is 1830/400 = 4.575, which implies 0.415.
    rating_avg, _ = rating_stats(RAW)
    old_gap = rating_sentiment_gap(rating_avg, df["compound_score"].mean())
    assert old_gap == pytest.approx(0.315)
    assert old_gap > 0.10


# ── category shares ───────────────────────────────────────────────────────────

def test_category_shares_are_post_stratified():
    # Two reviews per star; "battery" is in both 1-star, one 2-star, no
    # 3-star, one 4-star and one 5-star review: 5 mentions, 3 of them 1-2 star.
    texts = ["battery died", "battery bad", "battery meh", "fine",
             "ok", "ok", "battery good", "great", "battery great", "great"]
    ratings = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    with redirect_stdout(io.StringIO()):
        weighted = nlp.run_category_analysis(pd.Series(texts), pd.Series(ratings), RAW)
        sample = nlp.run_category_analysis(pd.Series(texts), pd.Series(ratings))

    battery = next(r for r in weighted if r["label"] == "Battery Life")
    assert battery["count"] == 5
    # rates 1.0, 0.5, 0, 0.5, 0.5 -> masses 0.025, 0.0125, 0, 0.075, 0.375
    assert battery["pct_negative"] == round(100 * 0.0375 / 0.4875, 1) == 7.7
    assert battery["pct_positive"] == round(100 * 0.45 / 0.4875, 1) == 92.3

    unweighted = next(r for r in sample if r["label"] == "Battery Life")
    assert (unweighted["pct_negative"], unweighted["pct_positive"]) == (60.0, 40.0)


# ── the committed data is what this code computes ─────────────────────────────

@pytest.mark.parametrize("path", FEATURE_FILES, ids=lambda p: Path(p).stem)
def test_cached_analysis_equals_a_fresh_one(path):
    """scripts/recompute_features.py ran on this code; a stale cache fails here.

    Compares the fields post-stratification changes, recomputed from the
    committed nlp_*.csv through the same `analyze_scored_reviews` the live
    pipeline runs after sentiment scoring.
    """
    blob = json.loads(Path(path).read_text())
    asin = Path(path).stem.removeprefix("features_")
    df = pd.read_csv(ROOT / "data" / "processed" / f"nlp_{asin}.csv")
    with redirect_stdout(io.StringIO()):
        fresh = nlp.analyze_scored_reviews(df, blob["summary"]["raw_star_distribution"])

    assert fresh["features"] == pytest.approx(blob["features"])
    for key in ("pct_negative", "pct_positive", "total_reviews", "avg_rating"):
        assert fresh["summary"][key] == blob["summary"][key], key
    assert fresh["summary"]["categories"] == blob["summary"]["categories"]
    assert fresh["summary"]["top_topics"] == blob["summary"]["top_topics"]


def test_served_negative_shares_left_the_sampling_baseline():
    """Every product sat at 27-38% because 40% of each sample is 1-2 star."""
    shown = [json.loads(Path(p).read_text())["summary"]["pct_negative"] for p in FEATURE_FILES]
    assert shown and max(shown) < 27.0
