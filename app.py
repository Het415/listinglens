import os
import json
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
# Define it here (Top level)
ENV_MODE = os.getenv("ENV_MODE", "production")
# ── App State ──────────────────────────────────────────────────────────────────
# We cache pipeline results in memory so we don't rerun NLP on every request
# This is the same pattern used in production ML serving systems

app_state = {}


# ── Lifespan ───────────────────────────────────────────────────────────────────

import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.ingest import SUPPORTED_ASINS
    app_state["supported_asins"] = SUPPORTED_ASINS
    app_state["cache"] = {}
    
    # start server immediately — load cache in background
    asyncio.create_task(preload_cache())
    
    yield
    print("Shutting down...")

async def preload_cache():
    """Loads all supported ASINs from cache in background after server starts."""
    await asyncio.sleep(3)
    
    supported = [
    "B08XPWDSWW", "B07GZFM1ZM", "B075X8471B", "B01K8B8YA8",
    "B07H65KP63", "B0791TX5P5", "B010BWYDYA", "B07S764D9V",
    "B0BW4PFM58", "B07PXGQC1Q", "B00N2ZDXW2", "B08RLW7918",
]
    
    for asin in supported:
        nlp_csv = f"data/processed/nlp_{asin}.csv"
        feat_json = f"data/processed/features_{asin}.json"
        
        if os.path.exists(nlp_csv) and os.path.exists(feat_json):
            print(f"Preloading {asin}...")
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda a=asin: run_full_pipeline(a))
                print(f"✓ {asin} loaded")
            except Exception as e:
                print(f"✗ {asin} failed: {e}")
        else:
            print(f"No cache files for {asin} — skipping")

# ── FastAPI App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ListingLens API",
    description="Amazon product intelligence platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: browser blocks cross-origin API calls unless the API echoes the request Origin.
# NEXT_PUBLIC_API_URL only tells the frontend *where* to call — CORS must allow your
# actual Vercel hostname (production, previews, or a custom domain).
_default_cors = (
    "https://listinglens-five.vercel.app,"
    "http://localhost:3000,http://127.0.0.1:3000"
)
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", _default_cors).split(",")
    if o.strip()
]
# Any *.vercel.app (production + preview URLs) unless disabled via CORS_ORIGIN_REGEX=""
_cors_regex_raw = os.getenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")
_cors_regex = _cors_regex_raw.strip() if _cors_regex_raw.strip().lower() not in ("", "none", "false") else None

_cors_kw: dict = {
    "allow_origins": _cors_origins,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if _cors_regex:
    _cors_kw["allow_origin_regex"] = _cors_regex

app.add_middleware(CORSMiddleware, **_cors_kw)

# ── Request/Response Models ────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    url_or_asin: str | None = None
    asin: str | None = None
    max_reviews: int = 250

class ChatRequest(BaseModel):
    asin: str
    question: str


# ── Helper ─────────────────────────────────────────────────────────────────────

def run_full_pipeline(asin: str, max_reviews: int = 250) -> dict:
    """
    Runs complete pipeline for one ASIN.
    In PRODUCTION: Strictly loads from disk.
    In DEVELOPMENT: Can trigger heavy ingestion if files are missing.
    """
    # 1. Memory cache hit
    if asin in app_state.get("cache", {}):
        return app_state["cache"][asin]

    nlp_csv   = f"data/processed/nlp_{asin}.csv"
    feat_json = f"data/processed/features_{asin}.json"

    # 2. Check for File Existence
    if os.path.exists(nlp_csv) and os.path.exists(feat_json):
        print(f"Loading pre-computed NLP for {asin}...")
        df_enriched = pd.read_csv(nlp_csv)
        with open(feat_json) as f:
            cached = json.load(f)
        features = cached["features"]
        summary  = cached["summary"]
    
    # 3. THE GUARDRAIL: If files are missing...
    else:
        if ENV_MODE == "production":
            # Throw a 404 so Railway never attempts the download
            print(f"Bailing out: ASIN {asin} not found in pre-computed data.")
            raise HTTPException(
                status_code=404,
                detail=f"Analysis for ASIN {asin} is not pre-computed. Please use a supported ASIN."
            )
        
        # ONLY runs in 'development' mode (your local machine)
        print(f"Dev Mode: Running heavy NLP pipeline for {asin}...")
        from src.ingest import get_reviews
        from src.nlp_pipeline import run_nlp_pipeline

        df, raw_distribution = get_reviews(
            asin,
            max_reviews=max_reviews,
            mode="huggingface",
        )
        if df.empty:
            raise HTTPException(status_code=404, detail="No reviews found.")

        nlp_result  = run_nlp_pipeline(df, raw_distribution=raw_distribution)
        df_enriched = nlp_result["df_enriched"]
        features    = nlp_result["features"]
        summary     = nlp_result["summary"]

        # Save for future use
        df_enriched.to_csv(nlp_csv, index=False)
        with open(feat_json, "w") as f:
            json.dump({"features": features, "summary": summary}, f)

    # ── Step 2: Fusion ──
    from src.fusion import run_fusion_pipeline
    risk = run_fusion_pipeline(features)

    # ── Assemble result ──
    result = {
        "asin":                asin,
        "product_name":        app_state["supported_asins"].get(asin, asin),
        "n_reviews":           len(df_enriched),
        "n_chunks":            None,
        "summary":             summary,
        "features":            features,
        "risk":                risk,
        "suggested_questions": [
    "Why are customers unhappy?",
    "What do 1-star reviews say?",
    "What features do customers like?"]
    }

    # cache in memory
    app_state["cache"][asin]          = result

    return result


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "ListingLens API",
        "version": "1.0.0",
    }


@app.get("/supported-asins")
def get_supported_asins():
    """Returns list of ASINs available for analysis."""
    from src.ingest import SUPPORTED_ASINS
    return {
        "asins": [
            {"asin": k, "name": v}
            for k, v in SUPPORTED_ASINS.items()
        ]
    }


@app.post("/analyze")
def analyze_product(request: AnalyzeRequest):
    """
    Main endpoint — runs full pipeline for a product URL or ASIN.

    Returns complete analysis: sentiment, topics, risk score, features.
    First call takes 3-5 minutes (NLP pipeline).
    Subsequent calls return cached results instantly.
    """
    from src.ingest import extract_asin
    try:
        asin = request.asin or extract_asin(request.url_or_asin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = run_full_pipeline(asin, request.max_reviews)
    return result


@app.post("/chat")
def chat(request: ChatRequest):
    chain_key = f"chain_{request.asin}"

    if chain_key not in app_state:
        from src.rag_chatbot import run_rag_pipeline

        # ensure analyze ran
        run_full_pipeline(request.asin)

        df_enriched = pd.read_csv(f"data/processed/nlp_{request.asin}.csv").head(100)
        rag = run_rag_pipeline(df_enriched, request.asin)

        app_state[chain_key] = rag["chain"]

    chain = app_state[chain_key]

    from src.rag_chatbot import ask_question
    result = ask_question(chain, request.question)

    return {
        "asin": request.asin,
        "question": request.question,
        "answer": result["answer"],
        "sources": result["sources"],
    }


@app.get("/analyze/{asin}")
def get_cached_analysis(asin: str):
    """
    Returns cached analysis for an ASIN without rerunning pipeline.
    Returns 404 if ASIN hasn't been analyzed yet.
    """
    if asin not in app_state.get("cache", {}):
        raise HTTPException(
            status_code=404,
            detail=f"ASIN {asin} not analyzed yet. Call POST /analyze first."
        )
    return app_state["cache"][asin]


@app.get("/analyze/{asin}/reviews")
def get_cached_reviews(asin: str):
    """
    Returns per-review rows from the cached NLP CSV.

    Reads `data/processed/nlp_{asin}.csv` generated by the NLP pipeline.
    """
    nlp_csv = f"data/processed/nlp_{asin}.csv"
    if not os.path.exists(nlp_csv):
        raise HTTPException(
            status_code=404,
            detail=f"Reviews for ASIN {asin} not found. Call POST /analyze first.",
        )

    df = pd.read_csv(nlp_csv)

    # Ensure required columns exist (older caches may be missing some).
    if "review_id" not in df.columns:
        df["review_id"] = list(range(len(df)))
    if "sentiment_label" not in df.columns:
        df["sentiment_label"] = "neutral"
    if "compound_score" not in df.columns:
        df["compound_score"] = 0.0
    if "topic_id" not in df.columns:
        df["topic_id"] = -1
    if "body" not in df.columns:
        df["body"] = ""

    # Keep payload reasonable for the UI.
    df = df.head(250)

    reviews = [
        {
            "review_id": int(row["review_id"]),
            "rating": int(row.get("rating", 0)),
            "sentiment_label": str(row["sentiment_label"]),
            "compound_score": float(row["compound_score"]),
            "topic_id": int(row["topic_id"]),
            "body": str(row["body"]),
        }
        for _, row in df.iterrows()
    ]

    return {
        "asin": asin,
        "total_reviews": len(reviews),
        "reviews": reviews,
    }


@app.get("/health")
def health():
    """Health check endpoint for Render deployment."""
    return {
        "status": "healthy",
        "cached_asins": list(app_state.get("cache", {}).keys()),
        "supported_asins": len(app_state.get("supported_asins", {})),
    }