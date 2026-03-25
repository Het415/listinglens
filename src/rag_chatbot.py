import os
import json
import time
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

os.environ["TOKENIZERS_PARALLELISM"] = "false"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Keep model configurable so deprecations don't break runtime.
# You can override in .env: GROQ_MODEL=...
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

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
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    cache_path = f"data/processed/vectorstore_{asin}"

    # load from cache if it exists — saves ~30 seconds per run
    if os.path.exists(cache_path):
        print(f"Loading cached vectorstore for {asin}...")
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
        )
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
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
    )

    # build FAISS index
    vectorstore = FAISS.from_documents(documents, embeddings)

    # save to disk
    os.makedirs("data/processed", exist_ok=True)
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

    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=0.1,
        max_tokens=512,
    )

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

            # 3. Retrieve
            docs = self.vectorstore.similarity_search(question, **search_kwargs)
            
            context = "\n\n".join(doc.page_content for doc in docs)
            prompt_text = self.prompt.format(context=context, question=question)
            
            answer = self.llm.invoke(prompt_text).content
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
    print(f"Using model: LLaMA 3 70B via Groq (free)")

    return {
        "chain":               chain,
        "vectorstore":         vectorstore,
        "suggested_questions": SUGGESTED_QUESTIONS,
        "n_chunks":            n_chunks,
    }