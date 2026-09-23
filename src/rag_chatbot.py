import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


def _get_embeddings():
    """Process-wide singleton for the MiniLM embeddings model.

    Backed by onnxruntime rather than sentence-transformers/torch: same
    checkpoint, same vectors (verified to cosine 1.000000 against the committed
    FAISS indexes), ~440MiB less RSS. That difference is the whole reason the
    RAG path fits on a small instance — see src/onnx_embeddings.py for the
    measurements. Reusing one instance across every ASIN's vectorstore still
    matters; the singleton now lives in that module.
    """
    from src.onnx_embeddings import get_embeddings

    return get_embeddings()

os.environ["TOKENIZERS_PARALLELISM"] = "false"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Vectorstore cache paths must be absolute. They used to be CWD-relative, so
# launching uvicorn from anywhere but the repo root silently missed every
# cached index and rebuilt it from scratch. Mirrors the pattern already used
# in backend/mcp_server/tools/_loader.py.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(REPO_ROOT, "data", "processed")

# FAISS pre-filters only `fetch_k` nearest neighbours and *then* applies a
# metadata filter, keeping the first `k` survivors. At the default fetch_k=20
# a rating-filtered query searches 20 chunks out of ~2900, so it returns
# fewer than k docs and the ones it does return are not the best matches for
# that rating. IndexFlatL2 over a few thousand vectors is exhaustive and
# costs microseconds, so we scan wide whenever a filter is active.
FILTERED_FETCH_K = 400

# ── Vector Store Builder ───────────────────────────────────────────────────────

def build_vectorstore(df_enriched: pd.DataFrame, asin: str):
    """
    Builds a FAISS vector store from review texts.

    Each review becomes one or more chunks.
    Each chunk is embedded using a local HuggingFace model (free, no API).
    The vector store is saved to disk so we don't rebuild on every query.

    Args:
        df_enriched: DataFrame from nlp_pipeline with sentiment columns
        asin: product ASIN — used for cache file naming

    Returns:
        FAISS vectorstore object
    """
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    cache_path = os.path.join(PROCESSED_DIR, f"vectorstore_{asin}")
    index_file = os.path.join(cache_path, "index.faiss")
    pkl_file = os.path.join(cache_path, "index.pkl")

    abs_cache = os.path.abspath(cache_path)
    exists_faiss = os.path.exists(index_file)
    exists_pkl = os.path.exists(pkl_file)
    print(
        f"[build_vectorstore] cache_path={abs_cache} "
        f"index.faiss={exists_faiss} index.pkl={exists_pkl}"
    )

    # FAISS.save_local writes both files; dir alone or one file is not valid cache
    if exists_faiss and exists_pkl:
        print(f"Loading cached vectorstore for {asin}...")
        embeddings = _get_embeddings()
        return FAISS.load_local(
            cache_path,
            embeddings,
            allow_dangerous_deserialization=True,
        )

    print(f"Building vectorstore for {asin}...")
    print("This takes ~30 seconds on first run")

    # chunk each review into passages
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n\n", "\n", ". ", " "],
    )

    documents = []
    for _, row in df_enriched.iterrows():
        # create chunks from this review
        chunks = splitter.split_text(str(row["body"]))

        for chunk in chunks:
            # skip very short chunks — no signal
            if len(chunk) < 50:
                continue

            # wrap in LangChain Document with metadata
            # metadata lets us filter and cite sources in answers
            doc = Document(
                page_content=chunk,
                metadata={
                    "review_id":       int(row.get("review_id", 0)),
                    "rating":          int(row.get("rating", 3)),
                    "sentiment_label": str(row.get("sentiment_label", "neutral")),
                    "compound_score":  float(row.get("compound_score", 0.0)),
                    "asin":            asin,
                },
            )
            documents.append(doc)

    print(f"Created {len(documents)} chunks from {len(df_enriched)} reviews")

    # embed using local sentence transformer — completely free
    embeddings = _get_embeddings()

    # build FAISS index
    vectorstore = FAISS.from_documents(documents, embeddings)

    # save to disk
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    vectorstore.save_local(cache_path)
    print(f"Vectorstore saved to {cache_path}")

    return vectorstore


# ── RAG Chain Builder ──────────────────────────────────────────────────────────
import re # Added for regex detection

# ... (Keep build_vectorstore as is, it's perfect)

# ── New Helper: Rating Detector ──────────────────────────────────────────────

def detect_rating_intent(question: str) -> int | None:
    """
    Simple regex to see if user is asking about a specific star rating.
    Example: "What do 1-star reviews say?" -> returns 1
    """
    match = re.search(r"(\d)[-\s]?star", question.lower())
    if match:
        rating = int(match.group(1))
        if 1 <= rating <= 5:
            return rating
    return None

# ── Updated RAG Chain Builder ──────────────────────────────────────────────

def build_rag_chain(vectorstore):
    from langchain_groq import ChatGroq
    from langchain_core.prompts import PromptTemplate

    from src.llm_config import rag_model, request_timeout, resilient_call

    # max_tokens is deliberately small. Groq enforces an *output* tokens per
    # minute cap (OTPM) separately from the input TPM cap, and it rejects a
    # request up front based on the output it *estimates* from max_tokens —
    # not on what the model actually produces. GROQ_MODEL's default
    # (qwen3.8-27b) has OTPM=1000, so max_tokens=1024 alone claims the whole
    # minute's budget and every call 429s before it runs. The prompt asks for
    # an answer "under 150 words" (~200 tokens), so 512 is ample.
    #
    # request_timeout caps the blocking wait. Without it, langchain retries a
    # 429 with backoff and no deadline, which hangs the /chat request (and the
    # uvicorn worker thread serving it) indefinitely rather than erroring. It
    # is the shared 20 s read timeout (was 60); see `stage_deadline_s` in
    # src/llm_config.py.
    _llms: dict = {}

    def llm_for(model: str):
        if model not in _llms:
            _llms[model] = ChatGroq(
                model=model,
                api_key=GROQ_API_KEY,
                temperature=0.1,
                max_tokens=512,
                request_timeout=request_timeout(),
                max_retries=1,
            )
        return _llms[model]

    llm = llm_for(rag_model())

    prompt_template = """You are a product analytics assistant. 
Use ONLY the following review excerpts. If you are filtering by a specific star rating, 
mention that in your answer (e.g., "Based on the 1-star reviews...").

Context:
{context}

Question: {question}

Answer (under 150 words):"""

    PROMPT = PromptTemplate(template=prompt_template, input_variables=["context", "question"])

    class SimpleRAGChain:
        def __init__(self, llm, vectorstore, prompt):
            self.llm = llm
            self.vectorstore = vectorstore # We use the store directly for filtering
            self.prompt = prompt

        def invoke(self, payload: dict) -> dict:
            question = payload.get("input", "").strip()
            
            # 1. Detect if the user wants a specific rating
            rating_filter = detect_rating_intent(question)
            
            # 2. Configure FAISS search
            # If a filter is found, we tell FAISS to ignore everything else
            search_kwargs = {"k": 5}
            if rating_filter:
                print(f"Applying Metadata Filter: rating == {rating_filter}")
                search_kwargs["filter"] = {"rating": rating_filter}
                # Widen the pre-filter sweep — see FILTERED_FETCH_K above.
                search_kwargs["fetch_k"] = FILTERED_FETCH_K

            # 3. Retrieve
            try:
                docs = self.vectorstore.similarity_search(question, **search_kwargs)
            except Exception as e:
                print(f"[RAG] similarity_search failed: {e}")
                raise

            # Never prompt the model with empty context — it would answer from
            # parametric memory and present it as grounded in reviews.
            if not docs:
                detail = (
                    f" with a {rating_filter}-star rating" if rating_filter else ""
                )
                return {
                    "answer": (
                        f"I couldn't find any reviews{detail} matching that "
                        f"question, so I have no review evidence to answer from."
                    ),
                    "context": [],
                }

            context = "\n\n".join(doc.page_content for doc in docs)
            prompt_text = self.prompt.format(context=context, question=question)
            
            try:
                # Fail over to the next model in the chain if this one has been
                # decommissioned or is rate-limited, instead of 500ing.
                answer = resilient_call(
                    "rag", lambda model: llm_for(model).invoke(prompt_text).content
                )
            except Exception as e:
                print(f"[RAG] Groq generation failed: {e}")
                raise
            return {"answer": answer, "context": docs}

    # Pass vectorstore instead of retriever for more control
    return SimpleRAGChain(llm, vectorstore, PROMPT)

# ... (Keep ask_question and run_rag_pipeline as is)


# ── Query Function ─────────────────────────────────────────────────────────────

def ask_question(chain, question: str) -> dict:
    """
    Asks a question about the product's reviews.

    Args:
        chain: RAG chain from build_rag_chain()
        question: seller's natural language question

    Returns dict with:
        answer:   LLM-generated answer grounded in reviews
        sources:  list of review chunks used to generate answer
        metadata: rating and sentiment of source reviews
    """
    print(f"\nQuestion: {question}")
    print("Retrieving relevant reviews...")

    result = chain.invoke({"input": question})

    # extract source review metadata
    sources = []
    for doc in result.get("context", []):
        sources.append({
            "text":      doc.page_content[:200],
            "rating":    doc.metadata.get("rating", "?"),
            "sentiment": doc.metadata.get("sentiment_label", "?"),
            "score":     doc.metadata.get("compound_score", 0),
        })

    return {
        "answer":   result.get("answer", ""),
        "sources":  sources,
        "n_sources": len(sources),
    }


# ── Suggested Questions ────────────────────────────────────────────────────────

SUGGESTED_QUESTIONS = [
    "Why are customers returning this product?",
    "What do 1-star reviewers complain about most?",
    "Which features do buyers love the most?",
    "What are the most common quality issues mentioned?",
    "How do customers describe the product after long-term use?",
]


# ── Main Pipeline Function ─────────────────────────────────────────────────────

def run_rag_pipeline(df_enriched: pd.DataFrame, asin: str) -> dict:
    """
    Master function called by app.py.
    Builds vectorstore and chain, returns them ready for queries.

    Args:
        df_enriched: enriched reviews DataFrame from nlp_pipeline
        asin: product ASIN

    Returns dict with:
        chain:              ready-to-query RAG chain
        vectorstore:        FAISS index (for inspection)
        suggested_questions: list of starter questions for the UI
        n_chunks:           how many chunks are in the vectorstore
    """
    print("\nInitializing RAG pipeline...")

    vectorstore = build_vectorstore(df_enriched, asin)
    chain = build_rag_chain(vectorstore)

    # get chunk count
    n_chunks = vectorstore.index.ntotal

    print(f"RAG pipeline ready — {n_chunks} chunks indexed")
    from src.llm_config import rag_model

    print(f"Using model: {rag_model()}")
    print(f"Using API key set: {bool(GROQ_API_KEY)}")

    return {
        "chain":               chain,
        "vectorstore":         vectorstore,
        "suggested_questions": SUGGESTED_QUESTIONS,
        "n_chunks":            n_chunks,
    }