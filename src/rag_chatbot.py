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

def build_rag_chain(vectorstore):
    """
    Builds a LangChain RAG chain using Groq as the LLM.

    Architecture:
        Question → FAISS retrieval (top 5 chunks) → Groq LLaMA 3 → Answer

    Why Groq: completely free, LLaMA 3 70B quality,
    faster than OpenAI for this use case.
    """
    from langchain_groq import ChatGroq
    from langchain_core.prompts import PromptTemplate

    # initialize Groq LLM
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=0.1,      # low temperature = factual, consistent answers
        max_tokens=512,
    )

    # custom prompt — tells LLM to stay grounded in retrieved reviews
    prompt_template = """You are a product analytics assistant helping an Amazon seller understand their customer feedback.

Use ONLY the following customer review excerpts to answer the question.
If the answer cannot be found in the reviews, say "I don't have enough review data to answer this confidently."
Never make up information or use general knowledge about the product.

Customer review excerpts:
{context}

Seller's question: {question}

Provide a clear, specific answer based on the reviews above.
Include specific details and patterns you observe across multiple reviews.
Keep your answer under 150 words."""

    PROMPT = PromptTemplate(
        template=prompt_template,
        input_variables=["context", "question"],
    )

    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 5},   # retrieve top 5 most relevant chunks
    )

    # Return a lightweight callable object so we don't depend on
    # rapidly-changing chain helper import paths across LangChain versions.
    class SimpleRAGChain:
        def __init__(self, llm, retriever, prompt):
            self.llm = llm
            self.retriever = retriever
            self.prompt = prompt

        def invoke(self, payload: dict) -> dict:
            question = payload.get("input", "").strip()
            docs = self.retriever.invoke(question) if question else []
            context = "\n\n".join(doc.page_content for doc in docs)
            prompt_text = self.prompt.format(context=context, question=question)
            try:
                answer = self.llm.invoke(prompt_text).content
            except Exception as e:
                msg = str(e).lower()
                if "decommissioned" in msg or "model_decommissioned" in msg:
                    raise RuntimeError(
                        f"Groq model '{GROQ_MODEL}' is decommissioned. "
                        "Set a supported model in .env via GROQ_MODEL."
                    ) from e
                raise
            return {"answer": answer, "context": docs}

    return SimpleRAGChain(llm, retriever, PROMPT)


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