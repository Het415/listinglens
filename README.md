# ListingLens — AI-Powered Amazon Seller Intelligence Platform

> Understand exactly why your product is failing — and what to do about it.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-black?style=for-the-badge)](https://listinglens-kappa.vercel.app)
[![Python](https://img.shields.io/badge/Python-3.13-green?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js-black?style=for-the-badge&logo=next.js)](https://nextjs.org)
[![XGBoost](https://img.shields.io/badge/ML-XGBoost-red?style=for-the-badge)](https://xgboost.readthedocs.io)
[![Groq](https://img.shields.io/badge/LLM-Groq%20LLaMA%203-orange?style=for-the-badge)](https://groq.com)

---

## What is ListingLens

ListingLens is a production-grade AI system that processes Amazon customer reviews and extracts actionable seller intelligence. It answers the questions every Amazon seller, retail analyst, and e-commerce team asks after a product launches: what are customers complaining about, how likely are buyers to return this product, and what specific changes would improve the listing?

The system combines transformer-based NLP, XGBoost prediction, and a RAG chatbot into a unified dashboard that any seller can interact with using plain English questions.

---

## Live Demo

**[listinglens-kappa.vercel.app](https://listinglens-kappa.vercel.app)**

Paste any supported ASIN (e.g. `B08XPWDSWW`) into the landing page to see the full analysis.

---

## The Problem This Solves

Amazon sellers see a star rating and a wall of unstructured review text. They have no systematic way to answer:

- *Why is my return rate 18% when my competitor's is 6%?*
- *Which specific complaint is killing my rating?*
- *Is my listing description setting the wrong expectations?*

Amazon Seller Central tells you **what** is happening. ListingLens tells you **why** — and what to do about it.

---

## System Architecture

```
Amazon ASIN
      ↓
  Data Layer
  HuggingFace Amazon Reviews 2023 Dataset
  250 reviews per product, balanced across all star ratings
      ↓
  NLP Pipeline
  ├── BERT Sentiment Analysis (HuggingFace Inference API)
  │   Per-review positive / neutral / negative scores + compound score
  └── LDA Topic Modeling (sklearn)
      Customer complaint and praise clusters with keyword extraction
      ↓
  Fusion Layer
  XGBoost Return Risk Classifier
  Trained on engineered proxy labels → HIGH / MEDIUM / LOW risk
      ↓
  RAG Pipeline
  ├── FAISS Vector Store (sentence-transformers/all-MiniLM-L6-v2)
  │   2,800+ review chunks embedded and indexed per product
  └── Groq LLaMA 3 70B
      Grounded Q&A — answers only from actual review text
      ↓
  FastAPI Backend + Next.js Frontend
```

---

## Features

### Sentiment Analysis
HuggingFace's RoBERTa model fine-tuned on social media text analyzes all 250 reviews and produces per-review sentiment scores. Reviews are balanced across star ratings (50 per star) before scoring to prevent skew toward 5-star dominated products. The compound score (positive minus negative probability) is the primary signal feeding downstream models.

### Return Risk Prediction
An XGBoost classifier trained on engineered features predicts return risk as HIGH, MEDIUM, or LOW. Key features include the percentage of negative reviews, average star rating, review-sentiment gap (detecting inflated ratings), and topic cluster signals. The model outputs an explainable risk score with plain-English reasoning.

### Topic Analysis
sklearn's LDA topic model with bigram support discovers what customers actually talk about without any manual labeling. Topics like "battery life", "sound quality", and "charging case" emerge automatically from the review text. Each topic shows both positive and negative sentiment percentages.

### RAG Chatbot
Sellers can ask any natural language question about their product's reviews and receive a grounded answer sourced directly from real customer text. A metadata filter detects star-rating intent in questions — asking about "1-star complaints" physically restricts retrieval to 1-star review chunks only, preventing the LLM from mixing in positive content.

### Competitor Compare
Side-by-side comparison of 2-3 products across return risk, sentiment, topics, and listing scores. Automatically highlights the winner with lowest return risk.

### Review Analysis
Deep-dive sentiment analysis page showing sentiment by star rating, topic breakdown with keyword clusters, and 5 auto-generated product insights.

### Export Report
One-click PDF report generation with executive summary, risk analysis, topic breakdown, and recommended actions. Downloads as a branded ListingLens PDF.

### Light/Dark Theme
Full theme switcher with animated reveal transition. Light mode default.

---

## The ML Design: Return Risk Proxy Labels

Real return rate data isn't publicly available — it lives in Amazon's internal systems. Rather than skip the prediction, I engineered a **proxy label** from signals that correlate with return behavior based on e-commerce research:

```python
risk_score = (
    pct_negative * 0.4 +            # negative review rate
    (1 - rating_avg / 5) * 0.4 +    # low average rating
    rating_sentiment_gap * 0.2       # mismatch between text sentiment and stars
)
label = 1 if risk_score > 0.30 else 0
```

The rating-sentiment gap is the most novel feature. It catches products where customers write relatively positive text but rate the product low — often a signal that the listing description created wrong expectations, a leading indicator of returns even before the star rating fully reflects it.

**Model performance:** 96.5% accuracy, 0.997 ROC-AUC on held-out data.

In production, this proxy would be replaced with actual return rate data from the seller's backend. The model architecture stays identical.

---

## RAG Pipeline: How It Works

**Step 1: Chunking** Each review is split into 300-character overlapping segments (50-char overlap), producing ~2,800 chunks per product.

**Step 2: Embedding** Every chunk is converted to a 384-dimensional vector using sentence-transformers all-MiniLM-L6-v2, running locally for zero cost.

**Step 3: Indexing** All chunk vectors are stored in a FAISS flat index with review metadata (star rating, sentiment label, compound score).

**Step 4: Metadata-Filtered Retrieval** The user's question is embedded and compared against the index. If a star-rating keyword is detected ("1-star", "complaints", "love"), a hard metadata filter restricts retrieval to only those review chunks before semantic search runs.

**Step 5: Generation** The top-5 retrieved chunks plus the question are sent to Groq's LLaMA 3 70B with a strict grounding prompt: *"Answer using ONLY these review excerpts."* The LLM cannot fabricate information beyond what customers actually wrote.

---

## Technical Stack

| Layer | Technology | Purpose |
|---|---|---|
| Sentiment | HuggingFace RoBERTa (router API) | Per-review sentiment scoring |
| Topic Modeling | sklearn LDA + bigram CountVectorizer | Customer complaint clustering |
| Return Risk | XGBoost classifier | Return probability prediction |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 | Review chunk vectorization |
| Vector Search | FAISS | Semantic similarity retrieval |
| LLM | Groq LLaMA 3 70B | Grounded answer generation |
| Backend | FastAPI + Uvicorn | REST API |
| Frontend | Next.js 16 + Tailwind CSS | Dashboard UI |
| Data Source | McAuley-Lab/Amazon-Reviews-2023 | Review dataset |
| Backend Hosting | Railway | Python API deployment |
| Frontend Hosting | Vercel | Next.js deployment |

---

## Supported Products

| ASIN | Product |
|---|---|
| B08XPWDSWW | TOZO T10 Bluetooth Earbuds |
| B07GZFM1ZM | Fire Stick 4K |
| B075X8471B | Fire TV Stick with Alexa |
| B01K8B8YA8 | Echo Dot 2nd Generation |
| B07H65KP63 | Echo Dot 3rd Generation |
| B0791TX5P5 | Fire TV Stick HD |
| B010BWYDYA | Fire Tablet 7 inch |
| B07S764D9V | Panasonic ErgoFit Wired Earbuds |
| B0BW4PFM58 | OontZ Angle 3 Bluetooth Speaker |
| B07PXGQC1Q | Apple AirPods 2nd Generation |
| B00N2ZDXW2 | Ring Video Doorbell |
| B08RLW7918 | WYZE Cam v2 Security Camera |

---

## Project Structure

```
listinglens/
├── src/
│   ├── ingest.py           Review fetching + star-rating balancing
│   ├── nlp_pipeline.py     BERT sentiment + LDA topic modeling
│   ├── fusion.py           XGBoost return risk classifier
│   └── rag_chatbot.py      FAISS vector store + Groq RAG chain
├── app.py                  FastAPI backend + startup preloading
├── precompute.py           Offline pipeline for adding new ASINs
├── data/processed/         Pre-computed NLP cache (CSV + JSON + FAISS)
└── frontend/               Next.js application
```

---

## Running Locally

**Prerequisites:** Python 3.11+, Node.js 18+

```bash
# Clone
git clone https://github.com/Het415/listinglens.git
cd listinglens

# Backend setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Environment variables — create .env with:
# GROQ_API_KEY=your_key
# HUGGINGFACE_API_KEY=your_key

# Start backend
uvicorn app:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open `http://localhost:3000`

---

## Adding New Products

Pre-compute NLP for a new ASIN locally, commit the cache files, and Railway auto-deploys:

```bash
python precompute.py --asin B07XJ8C8F7
git add data/processed/
git commit -m "add new product ASIN"
git push origin main
```

---

## What I Learned Building This

The most important engineering insight was that data quality matters more than model complexity. Balancing reviews to 50 per star rating before sentiment scoring was a bigger accuracy improvement than any model tuning — it removed the systematic bias from products with 90% five-star reviews masking real complaint patterns.

The most important product insight was that sellers need explanations, not just scores. Predicting return risk as a number is less useful than saying *"31% of reviews are negative and the rating-sentiment gap suggests the listing is creating wrong expectations."* The explainability layer was added because a number without context doesn't change seller behavior.

---

## Author

**Het Prajapati** — MS Data Science, Northeastern University (May 2027)

[LinkedIn](https://linkedin.com/in/het-prajapati6210) · [GitHub](https://github.com/Het415) · [Live Demo](https://listinglens-kappa.vercel.app)
