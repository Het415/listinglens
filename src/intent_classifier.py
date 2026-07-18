"""Customer-message intent classification.

Two-tier design, mirroring how real production intent systems hedge a cheap
fast model with an LLM safety net:

  1. Primary: a trained scikit-learn model (TF-IDF word+char n-grams ->
     LogisticRegression) persisted at data/processed/intent_model.joblib.
     Fast, offline, and cheap — handles the overwhelming majority of traffic.
  2. Fallback: a Groq LLM few-shot classifier, invoked ONLY when the sklearn
     model's top-class probability is below CONFIDENCE_THRESHOLD. Reuses the
     instructor + Groq structured-output pattern from the agent layer.

The label space is Bitext's `category` field (11 classes), which is already a
clean, product-support-flavored taxonomy. Training lives in
scripts/train_intent_model.py; this module is the runtime API used by the
conversation pipeline and the /intent/classify endpoint.
"""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "data" / "processed" / "intent_model.joblib"

# Below this top-class probability we don't trust the sklearn model and defer
# to the LLM. 0.55 keeps the LLM call rate low while still catching genuinely
# ambiguous / out-of-distribution messages.
CONFIDENCE_THRESHOLD = float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.55"))

# Bitext `category` -> human-friendly display label. This is the canonical
# taxonomy; the trained model's classes are the keys of this dict.
INTENT_LABELS: dict[str, str] = {
    "ACCOUNT": "Account & Access",
    "ORDER": "Order Management",
    "REFUND": "Refund",
    "INVOICE": "Invoice & Billing",
    "CONTACT": "Contact / Human Agent",
    "PAYMENT": "Payment",
    "FEEDBACK": "Feedback & Complaint",
    "DELIVERY": "Delivery",
    "SHIPPING": "Shipping",
    "SUBSCRIPTION": "Subscription",
    "CANCEL": "Cancellation",
}

CATEGORIES = list(INTENT_LABELS.keys())


def label_for(category: str) -> str:
    """Friendly display label for a raw category code."""
    return INTENT_LABELS.get(category, category.title())


# ── Trained sklearn model ────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_model():
    """Load the persisted sklearn pipeline. Returns None if not yet trained."""
    if not MODEL_PATH.exists():
        return None
    import joblib
    return joblib.load(MODEL_PATH)


def model_available() -> bool:
    return _load_model() is not None


def _predict_sklearn(text: str) -> tuple[str, float] | None:
    """(category, confidence) from the trained model, or None if unavailable."""
    model = _load_model()
    if model is None:
        return None
    proba = model.predict_proba([text])[0]
    classes = model.classes_
    idx = int(proba.argmax())
    return str(classes[idx]), float(proba[idx])


# ── LLM fallback ─────────────────────────────────────────────────────────────

def _intent_llm_model() -> str:
    # Cheap/fast model on its own Groq bucket — classification is a light task.
    return os.getenv("INTENT_LLM_MODEL", "llama-3.1-8b-instant")


@lru_cache(maxsize=1)
def _llm_client():
    import instructor
    from groq import Groq
    return instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))


def _predict_llm(text: str) -> tuple[str, float] | None:
    """Few-shot LLM classifier constrained to the CATEGORIES taxonomy.

    Returns (category, confidence) or None if the call fails (so callers can
    gracefully fall back to the sklearn guess).
    """
    from typing import Literal

    from pydantic import BaseModel, Field

    CategoryLiteral = Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]

    class IntentGuess(BaseModel):
        category: CategoryLiteral = Field(  # type: ignore[valid-type]
            description="The single best-matching support category for the message."
        )
        confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in the label.")

    system = (
        "You are an intent classifier for customer-support messages. "
        "Classify the message into exactly one of these categories:\n"
        + "\n".join(f"- {c}: {label_for(c)}" for c in CATEGORIES)
        + "\nReturn the category code (uppercase) and your confidence."
    )
    try:
        guess: IntentGuess = _llm_client().chat.completions.create(
            model=_intent_llm_model(),
            response_model=IntentGuess,
            max_retries=1,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        )
        return guess.category, float(guess.confidence)
    except Exception as e:  # noqa: BLE001 — fallback must never raise
        print(f"[intent] LLM fallback failed ({type(e).__name__}: {e})")
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def predict_intent(text: str, allow_llm: bool = True) -> dict:
    """Classify one customer message.

    Returns: {category, intent (friendly), confidence, source: 'model'|'llm'|'none'}.
    Uses the trained model first; only calls the LLM when the model is missing
    or under-confident and allow_llm is True.
    """
    text = (text or "").strip()
    if not text:
        return {"category": None, "intent": None, "confidence": 0.0, "source": "none"}

    sk = _predict_sklearn(text)

    if sk is not None and sk[1] >= CONFIDENCE_THRESHOLD:
        return {"category": sk[0], "intent": label_for(sk[0]),
                "confidence": round(sk[1], 4), "source": "model"}

    if allow_llm:
        llm = _predict_llm(text)
        if llm is not None:
            return {"category": llm[0], "intent": label_for(llm[0]),
                    "confidence": round(llm[1], 4), "source": "llm"}

    if sk is not None:
        # Under-confident model guess, but it's all we have.
        return {"category": sk[0], "intent": label_for(sk[0]),
                "confidence": round(sk[1], 4), "source": "model"}

    return {"category": None, "intent": None, "confidence": 0.0, "source": "none"}


def predict_batch(texts: list[str], allow_llm: bool = False) -> list[dict]:
    """Classify many messages. LLM fallback defaults OFF here to keep batch
    precompute fast and within Groq rate limits; per-message calls can opt in.
    """
    model = _load_model()
    if model is None:
        return [predict_intent(t, allow_llm=allow_llm) for t in texts]

    clean = [(t or "").strip() for t in texts]
    probas = model.predict_proba(clean)
    classes = model.classes_
    out: list[dict] = []
    for t, proba in zip(clean, probas):
        if not t:
            out.append({"category": None, "intent": None, "confidence": 0.0, "source": "none"})
            continue
        idx = int(proba.argmax())
        cat, conf = str(classes[idx]), float(proba[idx])
        if conf < CONFIDENCE_THRESHOLD and allow_llm:
            llm = _predict_llm(t)
            if llm is not None:
                out.append({"category": llm[0], "intent": label_for(llm[0]),
                            "confidence": round(llm[1], 4), "source": "llm"})
                continue
        out.append({"category": cat, "intent": label_for(cat),
                    "confidence": round(conf, 4), "source": "model"})
    return out


if __name__ == "__main__":
    import sys
    msg = " ".join(sys.argv[1:]) or "I want to return this broken speaker and get my money back"
    print(f"Message: {msg}")
    print(predict_intent(msg))
