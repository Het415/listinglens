"""Train/serve parity for the return-risk model (audit E-01, E-02, MDL-03).

The model was trained on one definition of its features and served another:
`rating_avg` came from a star-balanced sample (3.0 for every product), and
`rating_sentiment_gap` used a different formula on each side. These tests hold
both sides to src/features.py, and hold the served features to the region the
model was trained on.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pandas as pd
import pytest

import src.features as shared
import src.fusion as fusion
import src.nlp_pipeline as nlp
from src.features import MODEL_FEATURES, rating_sentiment_gap, rating_stats

ROOT = Path(__file__).resolve().parent.parent
FEATURE_FILES = sorted(glob.glob(str(ROOT / "data" / "processed" / "features_*.json")))


def _served(path: str) -> dict:
    return json.loads(Path(path).read_text())


@pytest.fixture(scope="module")
def training_ranges() -> dict[str, tuple[float, float]]:
    X, _, _ = fusion.generate_synthetic_training_data(n_samples=1000)
    return {name: (X[:, i].min(), X[:, i].max()) for i, name in enumerate(MODEL_FEATURES)}


def _fixture_reviews() -> tuple[pd.DataFrame, dict]:
    """Ten scored reviews, star-balanced like ingest's sample, plus a real
    distribution that is mostly 5-star."""
    ratings = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    compound = [-0.8, -0.6, -0.4, -0.2, 0.0, 0.1, 0.5, 0.6, 0.8, 0.9]
    df = pd.DataFrame({
        "body": [f"review {i}" for i in range(10)],
        "rating": ratings,
        "compound_score": compound,
        "positive_score": [max(c, 0) for c in compound],
        "negative_score": [max(-c, 0) for c in compound],
        "sentiment_label": ["negative"] * 4 + ["neutral"] * 2 + ["positive"] * 4,
    })
    raw = {"1": 5, "2": 5, "3": 10, "4": 30, "5": 150}
    return df, raw


# ── rating_avg is the real mean ────────────────────────────────────────────────

def test_rating_stats_is_the_mean_of_the_distribution():
    mean, std = rating_stats({"1": 1, "2": 0, "3": 0, "4": 0, "5": 1})
    assert mean == 3.0
    assert std == pytest.approx(2.0)
    assert rating_stats({1: 0, 2: 0, 3: 0, 4: 0, 5: 7}) == (5.0, 0.0)


def test_rating_stats_refuses_an_empty_distribution():
    with pytest.raises(ValueError):
        rating_stats({"1": 0, "2": 0, "3": 0, "4": 0, "5": 0})


def test_served_rating_avg_ignores_the_balanced_sample():
    """The sample below averages 3.0 by construction; the product does not."""
    df, raw = _fixture_reviews()
    assert df["rating"].mean() == 3.0
    _, features = nlp.engineer_features(df, [-1] * len(df), raw)
    assert features["rating_avg"] == pytest.approx(rating_stats(raw)[0])
    assert features["rating_avg"] == pytest.approx((5 + 10 + 30 + 120 + 750) / 200)


@pytest.mark.parametrize("path", FEATURE_FILES, ids=lambda p: Path(p).stem)
def test_cached_rating_avg_equals_the_raw_star_distribution_mean(path):
    blob = _served(path)
    mean, _ = rating_stats(blob["summary"]["raw_star_distribution"])
    assert blob["features"]["rating_avg"] == pytest.approx(mean)
    assert blob["summary"]["avg_rating"] == pytest.approx(round(mean, 2))


def test_no_product_is_served_the_balanced_sample_mean():
    """The E-01 signature: every product at exactly 3.0."""
    served = [_served(p)["features"]["rating_avg"] for p in FEATURE_FILES]
    assert served, "no cached features found"
    assert 3.0 not in served
    assert len(set(served)) > 1


# ── one gap, both sides ────────────────────────────────────────────────────────

def test_training_and_serving_import_the_same_gap_function():
    assert fusion.rating_sentiment_gap is shared.rating_sentiment_gap
    assert nlp.rating_sentiment_gap is shared.rating_sentiment_gap


def test_training_gap_equals_serving_gap_on_a_fixture():
    df, raw = _fixture_reviews()
    _, served = nlp.engineer_features(df, [-1] * len(df), raw)

    # What the training generator would write for the same product profile.
    trained = rating_sentiment_gap(served["rating_avg"], served["avg_compound_score"])
    assert served["rating_sentiment_gap"] == pytest.approx(trained)
    # And, spelled out, the formula the proxy label was defined with.
    expected = abs(served["avg_compound_score"] - (served["rating_avg"] / 5 - 0.5))
    assert served["rating_sentiment_gap"] == pytest.approx(expected)


def test_every_generated_row_uses_the_shared_gap():
    _, _, rows = fusion.generate_synthetic_training_data(n_samples=200)
    for row in rows:
        # The generator rounds rating_avg to 2dp and the others to 4dp, so a
        # recomputation from the stored values can differ by ~1e-3.
        recomputed = rating_sentiment_gap(row["rating_avg"], row["avg_compound_score"])
        assert row["rating_sentiment_gap"] == pytest.approx(recomputed, abs=2e-3)


# ── the vector the model sees ──────────────────────────────────────────────────

def test_served_features_are_exactly_the_model_inputs():
    df, raw = _fixture_reviews()
    _, features = nlp.engineer_features(df, [-1] * len(df), raw)
    assert tuple(features) == MODEL_FEATURES
    for path in FEATURE_FILES:
        assert tuple(_served(path)["features"]) == MODEL_FEATURES, path


def test_the_shipped_model_expects_this_many_features():
    model = fusion._load_return_risk_model()
    assert model.n_features_in_ == len(MODEL_FEATURES) == len(fusion.FEATURE_NAMES)


@pytest.mark.parametrize("path", FEATURE_FILES, ids=lambda p: Path(p).stem)
def test_every_served_feature_is_inside_its_training_range(path, training_ranges):
    features = _served(path)["features"]
    for name in MODEL_FEATURES:
        lo, hi = training_ranges[name]
        assert lo <= features[name] <= hi, f"{name}={features[name]} outside [{lo}, {hi}]"


def test_persisted_metrics_match_the_generator():
    metrics = json.loads((ROOT / fusion.METRICS_PATH).read_text())
    assert metrics["features"] == list(MODEL_FEATURES)
    assert "not a returns metric" in metrics["what_this_measures"]
    X, _, _ = fusion.generate_synthetic_training_data(n_samples=metrics["n_samples"])
    for i, name in enumerate(MODEL_FEATURES):
        lo, hi = metrics["training_ranges"][name]
        assert lo == pytest.approx(X[:, i].min(), abs=1e-4)
        assert hi == pytest.approx(X[:, i].max(), abs=1e-4)


# ── what the agent tools actually read ────────────────────────────────────────

@pytest.mark.parametrize("path", FEATURE_FILES, ids=lambda p: Path(p).stem)
def test_the_agents_loader_serves_the_same_features_as_the_files(path):
    """The runtime loader reads data/processed/listinglens.duckdb BEFORE the
    JSON, when that file exists. It is gitignored, so production and CI never
    have one and read the JSON. Locally, though, a stale warehouse silently
    wins: after the T-08 rebuild it still held the 3.0-star features, so the
    local Copilot, Brief and every local eval run kept the old numbers while
    /analyze showed the new ones. Rebuild it with `python -m scripts.build_duckdb`
    whenever the JSONs change; this test says when you forgot."""
    from backend.mcp_server.tools import _loader

    asin = Path(path).stem.replace("features_", "")
    blob = _served(path)
    assert _loader.asin_features(asin) == blob["features"]
    assert _loader.asin_summary(asin) == blob["summary"]
