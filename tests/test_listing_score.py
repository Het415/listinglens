"""The Overall Listing Score (src/fusion.listing_score).

The dashboard used to derive it as `(1 - risk_score) * 100`. risk_score is the
model's P(proxy label), and the label is a hard threshold with no noise, so the
model learned close to a step function. Once the features were fixed (E-01,
E-02), every real product sat far below the line, was served P ~= 0.001, and
showed 100/100. Before those fixes the same card showed 1-23 on 10 of 12. The
score now comes from the composite the label thresholds, which is continuous.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

import src.fusion as fusion

ROOT = Path(__file__).resolve().parent.parent
FEATURE_FILES = sorted(glob.glob(str(ROOT / "data" / "processed" / "features_*.json")))


def _features(pct_negative: float, rating_avg: float, gap: float) -> dict:
    # listing_score reads only the three label inputs.
    return {"pct_negative": pct_negative, "rating_avg": rating_avg,
            "rating_sentiment_gap": gap}


def _served_scores() -> dict[str, int]:
    return {
        Path(p).stem.replace("features_", ""):
            fusion.predict_return_risk(json.loads(Path(p).read_text())["features"])["listing_score"]
        for p in FEATURE_FILES
    }


# ── the scale ──────────────────────────────────────────────────────────────────

def test_a_perfect_product_scores_100():
    assert fusion.listing_score(_features(0.0, 5.0, 0.0)) == 100


def test_the_high_risk_line_scores_50():
    f = _features(0.75, 5.0, 0.0)
    assert fusion.proxy_risk_score(f) == pytest.approx(fusion.PROXY_HIGH_RISK_THRESHOLD)
    assert fusion.listing_score(f) == 50


def test_twice_the_line_or_worse_scores_0():
    assert fusion.listing_score(_features(0.75, 2.5, 0.5)) == 0   # composite 0.60
    assert fusion.listing_score(_features(1.0, 1.0, 1.0)) == 0    # composite 0.92


def test_each_input_moves_the_score_the_right_way():
    base = fusion.listing_score(_features(0.2, 4.3, 0.05))
    assert fusion.listing_score(_features(0.3, 4.3, 0.05)) < base
    assert fusion.listing_score(_features(0.2, 3.8, 0.05)) < base
    assert fusion.listing_score(_features(0.2, 4.3, 0.25)) < base


def test_the_score_agrees_with_the_label_it_shares_a_composite_with():
    _, y, rows = fusion.generate_synthetic_training_data(n_samples=1000)
    for label, row in zip(y, rows):
        score = fusion.listing_score(row)
        assert score <= 50 if label else score >= 50, (label, score, row)


# ── what the dashboard is served ───────────────────────────────────────────────

def test_the_risk_payload_carries_the_score():
    features = json.loads(Path(FEATURE_FILES[0]).read_text())["features"]
    risk = fusion.predict_return_risk(features)
    assert risk["listing_score"] == fusion.listing_score(features)


def test_the_cached_products_are_not_all_100():
    """The regression: under the old derivation all 12 showed 100."""
    scores = _served_scores()
    assert len(scores) == len(FEATURE_FILES) > 1
    assert all(0 < s < 100 for s in scores.values()), scores
    assert len(set(scores.values())) > 1, scores
