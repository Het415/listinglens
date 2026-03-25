import os
import json
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

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
    """Loads cache in background after server starts."""
    await asyncio.sleep(2)  # let server bind port first
    print("Background: loading pre-computed cache...")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: run_full_pipeline("B08XPWDSWW"))
        print("Background: cache loaded successfully")
    except Exception as e:
        print(f"Background: cache load failed: {e}")


# ── FastAPI App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ListingLens API",
    description="Amazon product intelligence platform",
    version="1.0.0",
    lifespan=lifespan,
)

# allow Next.js frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    Loads pre-computed NLP results from disk if available.
    Only runs NLP if no cache exists.
    """
    # return in-memory cache if available
    if asin in app_state.get("cache", {}):
        print(f"Memory cache hit for {asin}")
        return app_state["cache"][asin]

    nlp_csv   = f"data/processed/nlp_{asin}.csv"
    feat_json = f"data/processed/features_{asin}.json"

    # ── Step 1: Load or compute NLP results ──
    if os.path.exists(nlp_csv) and os.path.exists(feat_json):
        # load pre-computed results — instant
        print(f"Loading pre-computed NLP for {asin}...")
        df_enriched = pd.read_csv(nlp_csv)
        with open(feat_json) as f:
            cached = json.load(f)
        features = cached["features"]
        summary  = cached["summary"]

    else:
        # no cache — run full NLP pipeline
        # note: this takes 3-5 mins, only runs once per ASIN
        print(f"No cache found — running NLP pipeline for {asin}...")
        from src.ingest import get_reviews
        from src.nlp_pipeline import run_nlp_pipeline

        df = get_reviews(asin, max_reviews=max_reviews, mode="huggingface")
        if df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No reviews found for ASIN {asin}."
            )

        nlp_result  = run_nlp_pipeline(df)
        df_enriched = nlp_result["df_enriched"]
        features    = nlp_result["features"]
        summary     = nlp_result["summary"]

        # save to disk for future requests
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
    app_state[f"chain_{asin}"]        = rag["chain"]

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

        df_enriched = pd.read_csv(f"data/processed/nlp_{request.asin}.csv")
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


@app.get("/health")
def health():
    """Health check endpoint for Render deployment."""
    return {
        "status": "healthy",
        "cached_asins": list(app_state.get("cache", {}).keys()),
        "supported_asins": len(app_state.get("supported_asins", {})),
    }