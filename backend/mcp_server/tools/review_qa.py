"""review_qa tool — grounded Q&A over an ASIN's customer reviews.

Wraps the existing ListingLens RAG pipeline (src/rag_chatbot.py). The chain is
built once per ASIN and cached in-process so repeated agent calls don't pay
the FAISS-load + chain-construction cost on every iteration.
"""
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from ._loader import REPO_ROOT, asin_reviews_df

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_CHAIN_CACHE: dict = {}


class ReviewQAInput(BaseModel):
    asin: str = Field(..., description="10-character Amazon ASIN")
    question: str = Field(..., description="Natural-language question about reviews")


class ReviewSource(BaseModel):
    text: str
    rating: int
    sentiment: str
    score: float


class ReviewQAOutput(BaseModel):
    answer: str
    sources: list[ReviewSource]
    n_sources: int


def _get_chain(asin: str):
    if asin in _CHAIN_CACHE:
        return _CHAIN_CACHE[asin]

    from src.rag_chatbot import run_rag_pipeline

    df = asin_reviews_df(asin, limit=100)
    rag = run_rag_pipeline(df, asin)
    _CHAIN_CACHE[asin] = rag["chain"]
    return rag["chain"]


def review_qa(asin: str, question: str) -> dict:
    """Answers a question about an ASIN's reviews, grounded in retrieved chunks.

    Returns dict matching ReviewQAOutput. The agent sees only this — no FAISS
    or LangChain types leak out.
    """
    from src.rag_chatbot import ask_question

    chain = _get_chain(asin)
    result = ask_question(chain, question)

    out = ReviewQAOutput(
        answer=result["answer"],
        sources=[ReviewSource(**s) for s in result["sources"]],
        n_sources=result["n_sources"],
    )
    return out.model_dump()


TOOL_NAME = "review_qa"
TOOL_DESCRIPTION = (
    "Answer a natural-language question about an Amazon product's customer reviews. "
    "Returns a grounded answer with cited review excerpts. "
    "Use this when you need qualitative evidence from real customer feedback — "
    "complaints, praise, use cases, specific failure modes. "
    "If you mention a star rating in the question (e.g., 'what do 1-star reviews say?'), "
    "retrieval automatically filters to reviews of that rating."
)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="CLI for review_qa tool")
    parser.add_argument("asin", help="10-character ASIN")
    parser.add_argument("question", help="Question to ask")
    args = parser.parse_args()

    result = review_qa(args.asin, args.question)
    print(json.dumps(result, indent=2))
