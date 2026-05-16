"""predict_return_risk tool — quantitative return-risk score for an ASIN.

Wraps src/fusion.run_fusion_pipeline. Reads precomputed features from
data/processed/features_{asin}.json (no re-running the NLP pipeline).
"""
import sys

from pydantic import BaseModel, Field

from ._loader import REPO_ROOT, asin_features

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class ReturnRiskInput(BaseModel):
    asin: str = Field(..., description="10-character Amazon ASIN")


class ReturnRiskOutput(BaseModel):
    asin: str
    risk_score: float = Field(..., description="0-1 probability of HIGH return risk")
    risk_label: str = Field(..., description="HIGH | MEDIUM | LOW")
    risk_pct: float = Field(..., description="risk_score as percentage")
    confidence: float = Field(..., description="model confidence in the label")
    explanation: str = Field(..., description="Human-readable risk drivers")


def predict_return_risk(asin: str) -> dict:
    """Predicts return risk for an ASIN using cached NLP features + XGBoost model.

    The model is auto-trained on first call if data/processed/xgboost_model.json
    is missing (existing behavior in src/fusion.py).
    """
    from src.fusion import run_fusion_pipeline

    features = asin_features(asin)
    risk = run_fusion_pipeline(features)

    out = ReturnRiskOutput(asin=asin, **risk)
    return out.model_dump()


TOOL_NAME = "predict_return_risk"
TOOL_DESCRIPTION = (
    "Predict the return-risk level for an Amazon product based on its review signals. "
    "Returns a HIGH/MEDIUM/LOW label, a 0-1 probability score, and a plain-English "
    "explanation of the top risk drivers (e.g., 'pct_negative high, rating-sentiment gap'). "
    "Use this when the question is about returns, churn, customer dissatisfaction, "
    "or the quantitative risk of a product."
)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="CLI for predict_return_risk tool")
    parser.add_argument("asin", help="10-character ASIN")
    args = parser.parse_args()

    result = predict_return_risk(args.asin)
    print(json.dumps(result, indent=2))
