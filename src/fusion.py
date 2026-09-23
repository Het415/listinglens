import os
import json
from functools import lru_cache
import numpy as np
from dotenv import load_dotenv

from src.features import MODEL_FEATURES, rating_sentiment_gap

load_dotenv()

MODEL_PATH = "data/processed/xgboost_model.json"
# Written next to the model by train_model(), so the numbers quoted anywhere
# trace to a file rather than to memory (audit E-15).
METRICS_PATH = "data/processed/xgboost_metrics.json"


@lru_cache(maxsize=1)
def _load_return_risk_model():
    """Loads the XGBoost return-risk classifier once per process.

    Disk reads were happening on every predict call — small but adds up when
    the agent fires this tool several times per query.
    """
    import xgboost as xgb

    if not os.path.exists(MODEL_PATH):
        print("No trained model found — training now...")
        train_model()

    model = xgb.XGBClassifier()
    model.load_model(MODEL_PATH)
    return model

# ── Proxy Label Engineering ────────────────────────────────────────────────────

def create_proxy_labels(features_list: list[dict]) -> np.ndarray:
    """
    Creates proxy return risk labels when real return data isn't available.

    Logic: high return risk when a product has:
    - High negative sentiment (pct_negative > 0.35)
    - Low average rating (rating_avg < 3.0)
    - High rating-sentiment gap (customers say positive things but rate low)

    This proxy correlates with return behavior based on e-commerce research
    showing negative reviews and low ratings are the strongest return predictors.

    Be clear about what that makes the model: it learns this threshold of three
    of its own inputs, on synthetic rows. Its held-out accuracy measures how
    well it re-learns the formula, not anything about returns. The score it
    serves is P(proxy label = high risk), not a return rate.

    In production this would be replaced with actual return rate data
    from the seller's backend — the model architecture stays identical.
    """
    labels = []
    for f in features_list:
        # composite risk score from multiple signals
        risk_score = (
            f["pct_negative"] * 0.4 +
            (1 - f["rating_avg"] / 5) * 0.4 +
            f["rating_sentiment_gap"] * 0.2
        )
        # binary label: 1 = high return risk, 0 = low return risk
        labels.append(1 if risk_score > 0.30 else 0)
    return np.array(labels)


# ── Feature Vector Builder ─────────────────────────────────────────────────────

def build_feature_vector(features: dict) -> np.ndarray:
    """
    Converts features dict to ordered numpy array for XGBoost.
    Order must be consistent between training and inference: both follow
    src.features.MODEL_FEATURES.
    """
    return np.array([features[name] for name in MODEL_FEATURES], dtype=float)

FEATURE_NAMES = list(MODEL_FEATURES)


# ── Synthetic Training Data ────────────────────────────────────────────────────

def generate_synthetic_training_data(n_samples: int = 500) -> tuple:
    """
    Generates synthetic training data for XGBoost.

    Why synthetic: we have features for one product (TOZO earbuds).
    XGBoost needs many products to learn patterns.

    We generate realistic product profiles by sampling from
    distributions that mirror real e-commerce data, then
    apply the same proxy label logic.

    In production: replace with real features from 100+ products
    scraped from the HuggingFace dataset.
    """
    np.random.seed(42)

    features_list = []
    for _ in range(n_samples):
        # simulate a product's aggregated review signals
        rating_avg = np.random.uniform(1.5, 5.0)

        # sentiment correlates with rating but with noise
        base_positive = (rating_avg - 1) / 4
        pct_positive = np.clip(
            base_positive + np.random.normal(0, 0.15), 0.05, 0.95
        )
        pct_negative = np.clip(
            (1 - base_positive) * 0.6 + np.random.normal(0, 0.1), 0.02, 0.80
        )

        avg_positive_score = np.clip(
            pct_positive + np.random.normal(0, 0.05), 0.1, 0.95
        )
        avg_negative_score = np.clip(
            pct_negative + np.random.normal(0, 0.05), 0.05, 0.85
        )
        avg_compound = avg_positive_score - avg_negative_score

        features = {
            "avg_compound_score":   round(avg_compound, 4),
            "pct_negative":         round(pct_negative, 4),
            "pct_positive":         round(pct_positive, 4),
            "avg_positive_score":   round(avg_positive_score, 4),
            "avg_negative_score":   round(avg_negative_score, 4),
            "rating_avg":           round(rating_avg, 2),
            # The same function serving uses (src/features.py).
            "rating_sentiment_gap": round(rating_sentiment_gap(rating_avg, avg_compound), 4),
        }
        features_list.append(features)

    X = np.array([build_feature_vector(f) for f in features_list])
    y = create_proxy_labels(features_list)

    return X, y, features_list


# ── Model Training ─────────────────────────────────────────────────────────────

def train_model():
    """
    Trains XGBoost return risk classifier on synthetic data.
    Saves model to disk for reuse.

    Returns trained model and evaluation metrics.
    """
    import xgboost as xgb
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import (
        classification_report,
        roc_auc_score,
        accuracy_score,
    )

    print("Generating training data...")
    X, y, _ = generate_synthetic_training_data(n_samples=1000)

    print(f"Training samples: {len(X)}")
    print(f"Class distribution: {y.mean():.1%} high risk, "
          f"{1-y.mean():.1%} low risk")

    # train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # train XGBoost
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy":  round(accuracy_score(y_test, y_pred), 4),
        "roc_auc":   round(roc_auc_score(y_test, y_prob), 4),
        "report":    classification_report(y_test, y_pred),
    }

    print(f"\nModel performance:")
    print(f"  Accuracy: {metrics['accuracy']}")
    print(f"  ROC-AUC:  {metrics['roc_auc']}")

    # feature importance
    importance = dict(zip(FEATURE_NAMES, model.feature_importances_))
    importance = dict(sorted(importance.items(),
                             key=lambda x: x[1], reverse=True))
    print("\nTop features:")
    for feat, imp in list(importance.items())[:5]:
        print(f"  {feat}: {imp:.4f}")

    # save model
    os.makedirs("data/processed", exist_ok=True)
    model.save_model(MODEL_PATH)
    print(f"\nModel saved to {MODEL_PATH}")

    # ...and what it scored, next to it. The ranges are what the parity test
    # checks served features against.
    X_all = np.vstack([X_train, X_test])
    with open(METRICS_PATH, "w") as f:
        json.dump({
            "what_this_measures": (
                "Held-out agreement with a synthetic proxy label that is a "
                "threshold of three of the model's own inputs "
                "(create_proxy_labels). It is not a returns metric."
            ),
            "accuracy": metrics["accuracy"],
            "roc_auc": metrics["roc_auc"],
            "n_samples": int(len(X)),
            "n_test": int(len(X_test)),
            "positive_rate": round(float(y.mean()), 4),
            "features": FEATURE_NAMES,
            "feature_importance": {k: round(float(v), 4) for k, v in importance.items()},
            "training_ranges": {
                name: [round(float(X_all[:, i].min()), 4), round(float(X_all[:, i].max()), 4)]
                for i, name in enumerate(FEATURE_NAMES)
            },
            "xgboost_version": xgb.__version__,
            "seed": 42,
        }, f, indent=2)
        f.write("\n")
    print(f"Metrics saved to {METRICS_PATH}")

    return model, metrics


# ── Inference ──────────────────────────────────────────────────────────────────

def predict_return_risk(features: dict) -> dict:
    """
    Predicts return risk for a single product given its NLP features.

    Loads trained model from disk.
    Returns risk score, label, and confidence.

    Args:
        features: dict from nlp_pipeline.engineer_features()

    Returns dict with:
        risk_score:  float 0-1 (probability of high return risk)
        risk_label:  "HIGH" | "MEDIUM" | "LOW"
        confidence:  float 0-1
        explanation: human-readable explanation
    """
    model = _load_return_risk_model()

    # build feature vector
    X = build_feature_vector(features).reshape(1, -1)

    # predict
    risk_prob = model.predict_proba(X)[0][1]  # probability of high risk

    # categorize risk
    if risk_prob >= 0.55:
        risk_label = "HIGH"
    elif risk_prob >= 0.25:
        risk_label = "MEDIUM"
    else:
        risk_label = "LOW"

    # generate explanation based on top risk drivers
    explanation = _generate_risk_explanation(features, risk_prob)

    return {
        "risk_score":   round(float(risk_prob), 4),
        "risk_label":   risk_label,
        "risk_pct":     round(float(risk_prob) * 100, 1),
        "confidence":   round(float(max(risk_prob, 1 - risk_prob)), 4),
        "explanation":  explanation,
    }


def _generate_risk_explanation(features: dict, risk_prob: float) -> str:
    """
    Generates a human-readable explanation of the risk prediction.
    Rule-based — fast, transparent, no LLM needed for this part.
    """
    drivers = []

    # `pct_negative` is the sentiment model's share of reviews labelled
    # negative, weighted to the product's real star mix (src/features.py). It
    # is not the 1-2 star share, which can be far lower (B07GZFM1ZM: 27% read
    # as negative, 8.5% rated 1-2 stars), hence "read as".
    if features["pct_negative"] > 0.25:
        drivers.append(
            f"{features['pct_negative']*100:.0f}% of reviews read as negative"
        )

    if features["rating_avg"] < 3.5:
        drivers.append(
            f"average rating is low at {features['rating_avg']:.1f}/5"
        )

    if features["rating_sentiment_gap"] > 0.10:
        drivers.append(
            "significant gap between ratings and review sentiment"
        )

    if features["avg_compound_score"] < 0.1:
        drivers.append(
            "overall sentiment is negative"
        )

    if not drivers:
        drivers.append("product signals look healthy")

    return "Risk drivers: " + "; ".join(drivers)


# ── Main ───────────────────────────────────────────────────────────────────────

def run_fusion_pipeline(nlp_features: dict) -> dict:
    """
    Master function called by app.py.
    Takes NLP features, returns complete risk assessment.
    """
    print("\nRunning fusion pipeline...")
    risk = predict_return_risk(nlp_features)
    print(f"Return risk: {risk['risk_label']} ({risk['risk_pct']}%)")
    print(f"Explanation: {risk['explanation']}")
    return risk