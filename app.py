import os
import json
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
# Define it here (Top level)
ENV_MODE = os.getenv("ENV_MODE", "production")
# ── App State ──────────────────────────────────────────────────────────────────
# We cache pipeline results in memory so we don't rerun NLP on every request
# This is the same pattern used in production ML serving systems

app_state = {}

def has_precomputed_cache(asin: str) -> bool:
    """True only if both NLP CSV + features JSON exist on disk."""
    nlp_csv = f"data/processed/nlp_{asin}.csv"
    feat_json = f"data/processed/features_{asin}.json"
    return os.path.exists(nlp_csv) and os.path.exists(feat_json)


# ── Lifespan ───────────────────────────────────────────────────────────────────

import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.ingest import SUPPORTED_ASINS
    # In production, only advertise ASINs that are truly precomputed on disk.
    if ENV_MODE == "production":
        app_state["supported_asins"] = {
            asin: name for asin, name in SUPPORTED_ASINS.items() if has_precomputed_cache(asin)
        }
    else:
        app_state["supported_asins"] = SUPPORTED_ASINS
    app_state["cache"] = {}

    # Opt-in: the background preload sequentially fires the full NLP+FAISS
    # pipeline for every supported ASIN, which on Render's free tier spikes
    # RAM/CPU and contends with the first real request. Default to OFF in
    # production; flip PRELOAD_CACHE=1 locally if you want a warm cache after
    # boot.
    if os.getenv("PRELOAD_CACHE", "0") == "1":
        asyncio.create_task(preload_cache())

    yield
    print("Shutting down...")

async def preload_cache():
    """Loads all supported ASINs from cache in background after server starts."""
    await asyncio.sleep(3)
    supported_asins = list(app_state.get("supported_asins", {}).keys())
    for asin in supported_asins:
        # In production, supported_asins is already filtered to disk cache availability.
        # In development, this might still include missing items, but run_full_pipeline
        # will handle it (it can compute missing caches in dev mode).
        print(f"Preloading {asin}...")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda a=asin: run_full_pipeline(a))
            print(f"✓ {asin} loaded")
        except Exception as e:
            print(f"✗ {asin} failed: {e}")

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
    # Vercel-hosted production URLs.
    "https://listinglens-kappa.vercel.app,"
    "https://listinglens-five.vercel.app,"
    # Custom production domain.
    "https://listinglens.hetprajapati.me,"
    # Local dev.
    "http://localhost:3000,http://127.0.0.1:3000"
)
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", _default_cors).split(",")
    if o.strip()
]
# Any *.vercel.app (production + preview URLs) and any *.hetprajapati.me subdomain
# (custom domain + future previews) unless disabled via CORS_ORIGIN_REGEX=""
_cors_regex_raw = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https://([a-z0-9-]+\.)*(vercel\.app|hetprajapati\.me)",
)
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


class AgentQueryRequest(BaseModel):
    asin: str
    query: str


class AssistantQueryRequest(BaseModel):
    asin: str
    query: str
    # User explicitly picks the mode via the segmented toggle on /assistant.
    # "quick"   → review_qa only (fast grounded Q&A)
    # "copilot" → full Planner→Executor→Synthesizer agent
    mode: str = "copilot"


class WarmupRequest(BaseModel):
    asin: str | None = None


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
    return {
        "asins": [
            {"asin": k, "name": v}
            for k, v in app_state.get("supported_asins", {}).items()
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
    if not request.asin and not request.url_or_asin:
        raise HTTPException(status_code=400, detail="Provide `asin` or `url_or_asin`")
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
    Returns analysis for an ASIN.

    Serves from the in-memory cache when warm. On a cold cache (fresh deploy,
    process restart, or a second worker that didn't handle the POST) it falls
    back to `run_full_pipeline`, which loads the pre-computed data from disk.
    This avoids spurious 404s on Render's free tier (which spins the service
    down on inactivity and loses the in-memory cache). Still 404s via the
    pipeline's production guardrail if the ASIN has no pre-computed data.
    """
    if asin in app_state.get("cache", {}):
        return app_state["cache"][asin]
    return run_full_pipeline(asin)


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


@app.post("/agent/query")
async def agent_query(request: AgentQueryRequest):
    """Stage 5: streaming agent endpoint.

    Returns Server-Sent Events as the multi-node agent progresses:
      planner_done → executor (tool_call/tool_result) loop → synthesizer → done.

    The agent code is imported INSIDE this handler so any import-time
    failure in backend.agent.* doesn't take down the existing /analyze
    and /chat endpoints during a Render cold start.
    """
    try:
        from backend.agent.graph import run_agent_streaming
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Agent layer unavailable: {type(e).__name__}: {e}",
        )

    async def event_stream():
        try:
            async for event in run_agent_streaming(request.asin, request.query):
                payload = json.dumps(event["data"], default=str)
                yield f"event: {event['event']}\ndata: {payload}\n\n"
        except Exception as e:
            err = json.dumps({"message": f"{type(e).__name__}: {e}"})
            yield f"event: error\ndata: {err}\n\n"

    # Redis cache wrapper — degrades to passthrough if REDIS_URL is unset
    # or Redis is unreachable. Key includes mode="agent" to keep
    # /agent/query and /assistant/query namespaces separate even when the
    # (asin, query) pair is identical.
    from backend.cache import cached_sse_stream, make_key
    cache_key = make_key(request.asin, request.query, mode="agent")

    return StreamingResponse(
        cached_sse_stream(cache_key, event_stream()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disables nginx buffering on Render
        },
    )


@app.post("/agent/query/mock")
async def agent_query_mock(request: AgentQueryRequest):
    """Stage 5 frontend-dev fixture: streams a canned trace without calling
    Groq. Same SSE shape as the live /agent/query endpoint, so frontend code
    is identical between mock and live.

    The `query` and `asin` fields are ignored — the fixture always streams
    the canonical TOZO-T10 returns scenario.
    """
    try:
        from backend.agent.mock_stream import stream_mock_returns
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Mock stream unavailable: {type(e).__name__}: {e}",
        )

    async def event_stream():
        async for event in stream_mock_returns():
            payload = json.dumps(event["data"], default=str)
            yield f"event: {event['event']}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/assistant/query")
async def assistant_query(request: AssistantQueryRequest):
    """Unified entry point for any seller question.

    The user picks the mode explicitly via the /assistant segmented toggle:
      - "quick"   → review_qa directly (~5s, grounded answer + sources)
      - "copilot" → full Planner→Executor→Synthesizer agent (~10-30s,
                    structured Recommendation + tools trace)

    All events use the same vocabulary as /agent/query so the TracePanel
    is reusable. The quick path adds a terminal `answer` event (the quick
    analogue of `recommendation`).
    """
    mode = request.mode if request.mode in ("quick", "copilot") else "copilot"

    async def event_stream():
        # First event echoes the routed mode so the frontend can confirm.
        yield f"event: kind\ndata: {json.dumps({'value': mode})}\n\n"

        if mode == "copilot":
            try:
                from backend.agent.graph import run_agent_streaming
            except Exception as e:
                err = json.dumps({"message": f"Agent unavailable: {type(e).__name__}: {e}"})
                yield f"event: error\ndata: {err}\n\n"
                return

            try:
                async for event in run_agent_streaming(request.asin, request.query):
                    payload = json.dumps(event["data"], default=str)
                    yield f"event: {event['event']}\ndata: {payload}\n\n"
            except Exception as e:
                err = json.dumps({"message": f"{type(e).__name__}: {e}"})
                yield f"event: error\ndata: {err}\n\n"
            return

        # 2. Quick path — emit a minimal trace so TracePanel renders something,
        #    then call review_qa, then emit the `answer` payload.
        try:
            from backend.mcp_server.tools.review_qa import review_qa
            from backend.mcp_server.tools._loader import supported_asins
        except Exception as e:
            err = json.dumps({"message": f"review_qa unavailable: {type(e).__name__}: {e}"})
            yield f"event: error\ndata: {err}\n\n"
            return

        catalog = supported_asins()
        if request.asin not in catalog:
            err = json.dumps({
                "message": f"Unknown ASIN: {request.asin}",
                "known": sorted(catalog.keys()),
            })
            yield f"event: error\ndata: {err}\n\n"
            return
        product_name = catalog[request.asin]

        yield (
            "event: started\n"
            f"data: {json.dumps({'asin': request.asin, 'product_name': product_name, 'query': request.query})}\n\n"
        )
        yield (
            "event: node_started\n"
            f"data: {json.dumps({'node': 'review_qa', 'label': 'searching reviews'})}\n\n"
        )
        yield (
            "event: tool_call\n"
            f"data: {json.dumps({'tool': 'review_qa', 'args': {'asin': request.asin, 'question': request.query}})}\n\n"
        )

        try:
            # review_qa is synchronous (FAISS retrieval + Groq LLM). Run it
            # in a worker thread so the event loop stays free to flush SSE
            # frames; asyncio.to_thread uses the default thread executor and
            # plays well with the upstream FAISS/Bert init.
            result = await asyncio.to_thread(review_qa, request.asin, request.query)
        except Exception as e:
            err = json.dumps({"message": f"{type(e).__name__}: {e}"})
            yield f"event: error\ndata: {err}\n\n"
            return

        preview = (result.get("answer") or "")[:200]
        yield (
            "event: tool_result\n"
            f"data: {json.dumps({'tool': 'review_qa', 'result_preview': preview})}\n\n"
        )
        yield (
            "event: node_completed\n"
            f"data: {json.dumps({'node': 'review_qa'})}\n\n"
        )
        yield (
            "event: answer\n"
            f"data: {json.dumps({'content': result.get('answer', ''), 'sources': result.get('sources', []), 'n_sources': result.get('n_sources', 0)}, default=str)}\n\n"
        )
        yield "event: done\ndata: {}\n\n"

    # Cache by (asin, query, mode). Quick and copilot modes produce
    # very different traces for the same question, so the mode is part
    # of the key — never serve a quick-mode trace to a copilot caller.
    from backend.cache import cached_sse_stream, make_key
    cache_key = make_key(request.asin, request.query, mode=f"assistant:{mode}")

    return StreamingResponse(
        cached_sse_stream(cache_key, event_stream()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/competitors/{asin}")
def get_competitors(asin: str, max_results: int = 5):
    """Returns synthetic competitor cards for an ASIN's category.

    Thin wrapper around the `competitor_search` MCP tool so the frontend
    can pre-populate the Compare page and the dashboard's market-context
    panel without spinning up the full agent. The competitor ASINs are
    *mock data* and intentionally outside the analyzed catalog — see
    `backend/data/mock_market_data.json` and `eval/README.md` for the
    v1 mock policy. Clients should label these as synthetic.
    """
    try:
        from backend.mcp_server.tools.competitor import competitor_search

        return competitor_search(asin, max_results=max_results)
    except ValueError as e:
        # competitor_search raises ValueError for unknown ASINs; map to 404
        # so the frontend can render an empty-state instead of an error toast.
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/health")
def health():
    """Health check endpoint for Render deployment."""
    return {
        "status": "healthy",
        "cached_asins": list(app_state.get("cache", {}).keys()),
        "supported_asins": len(app_state.get("supported_asins", {})),
    }


def _warm_asin_sync(asin: str) -> None:
    """Blocking worker — loads FAISS chain + compiles LangGraph for one ASIN.

    Runs in a thread executor so the /warmup request returns immediately.
    Failures are swallowed and logged; warmup is best-effort.
    """
    try:
        # Hydrate the in-memory NLP/risk cache and disk-cached FAISS index.
        run_full_pipeline(asin)
        df_enriched = pd.read_csv(f"data/processed/nlp_{asin}.csv").head(100)
        from src.rag_chatbot import run_rag_pipeline

        rag = run_rag_pipeline(df_enriched, asin)
        app_state[f"chain_{asin}"] = rag["chain"]
    except Exception as e:
        print(f"[warmup] chain warmup failed for {asin}: {e}")

    try:
        from backend.agent.graph import build_graph

        build_graph(asin)
    except Exception as e:
        print(f"[warmup] graph warmup failed for {asin}: {e}")


@app.post("/warmup")
async def warmup(req: WarmupRequest):
    """Fire-and-forget warmup. Returns immediately; loads heavy resources in
    a background thread so the next real request to /chat or /agent/query
    skips the cold load.
    """
    supported = app_state.get("supported_asins", {})
    asin = req.asin if req.asin and req.asin in supported else next(iter(supported), None)
    if not asin:
        return {"warmed": False, "reason": "no supported ASINs"}

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _warm_asin_sync, asin)
    return {"warmed": True, "asin": asin}