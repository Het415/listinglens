# Build Plan — Visual Product Retrieval Service + ListingLens Integration

**Owner:** Het Prajapati
**Target:** Project A from the portfolio plan. Closes the computer vision, PyTorch training, personalization, and scale gaps.
**Intended use:** hand this to Claude Code as the working spec. One milestone per session.

---

## 0. Shape of the thing

**Two repos, one integration.**

- **New repo (`vislens` or similar):** training code, Spark embedding job, FAISS index, FastAPI retrieval service. Deployed independently. Has its own README, its own metrics table, its own resume line.
- **ListingLens:** gains one new tool, `visual_competitor_search`, which is a thin HTTP client to that service. This is the "extend the existing repo" part — ListingLens replaces a synthetic tool with a real one.

Why not one repo: the fine-tuned vision encoder would push the ListingLens container past what the current free-tier deployment can carry, and the CV work would be invisible on a resume that lists projects as discrete lines. Separate service, wired in, gets both.

**Everything the service exposes:**

```
POST /search/image     → multipart image, returns ranked products
POST /search/text      → text query, returns ranked products
POST /search/hybrid    → image + text, weighted fusion
GET  /healthz
GET  /metrics          → latency histogram, index size, model version
```

---

## 1. Dataset decision

**Primary: Amazon Berkeley Objects (ABO).** ~147K products, product images, structured metadata (brand, color, product_type, item_name), permissive license, and it is real Amazon catalog data, which keeps the ListingLens story coherent.

**Fallback: Fashion Product Images (Kaggle), ~44K items.** Use this if compute turns out to be tight, or as the fast iteration set while the pipeline is being debugged.

Structural detail Claude Code must handle correctly: ABO listings reference images by `main_image_id` and `other_image_id`, and the actual file paths live in a separate images metadata CSV. The join is required; there is no direct path field on the listing. Titles are multilingual — filter to `en_US` before doing anything with text.

**Do not commit data or model weights.** Download script plus `.gitignore`. Weights go to a release artifact or HF Hub if they need to be shareable.

---

## 2. Milestones

Each milestone ends in something demonstrable. If the project stops after M2 it is still a resume line.

### M0 — Scaffolding and data pipeline (~1 week)

**Build:**
- Repo skeleton mirroring ListingLens conventions: `src/`, `scripts/`, `eval/`, `tests/`, `docs/`, pre-commit with ruff, pytest, pinned Python version.
- `scripts/download_data.py` — fetches ABO, verifies checksums, idempotent.
- `scripts/build_catalog.py` — parses listings, joins the image metadata, filters to `en_US`, drops products without a usable main image, normalizes fields, writes `catalog.parquet` with columns: `product_id, title, brand, product_type, color, image_path, image_width, image_height`.
- Long-tail handling: cap `product_type` to the top N classes covering ~90% of items, bucket the rest as `other`. Log the distribution.
- **Split by `product_id`, never by image.** A product with five images must have all five in the same split, or the retrieval eval is leaking. Write a test that asserts zero product overlap across splits.
- `docs/data_card.md` — row counts, class distribution, known quirks, license terms.

**Acceptance:** `pytest` green, `catalog.parquet` built reproducibly from a clean clone, split-leakage test passing, data card written.

---

### M1 — Vision encoder fine-tune (~1 week)

This is the milestone that closes the PyTorch and CV gaps. Do not skip the baselines; they are what make the numbers mean anything.

**Build, in this order:**
1. **Frozen baseline** — ImageNet-pretrained ResNet-50, features extracted, linear probe on `product_type`. Record top-1 and top-5.
2. **Full fine-tune** — same architecture, unfrozen, with augmentation (random resized crop, horizontal flip, color jitter), cosine LR schedule with warmup, mixed precision, early stopping on val top-1.
3. **ViT-B/16 fine-tune** — only if compute allows. If it doesn't, say so in the README rather than omitting it silently.

**Engineering requirements:**
- Config-driven runs (YAML or Hydra), config hash logged with every run.
- Weights & Biases logging: loss, LR, val metrics, sample predictions.
- Deterministic seeding, documented.
- Checkpoint on best val metric, not last epoch.
- `DataLoader` reading from the parquet manifest with lazy image loading. Do not load the image set into memory.

**Acceptance:** a markdown table in the README comparing all trained variants against the frozen baseline, plus committed loss curves. The delta over the frozen baseline is the headline, not the absolute accuracy.

---

### M2 — Two-tower contrastive retrieval (~1.5 weeks)

**Architecture:**
- Image tower: the fine-tuned encoder from M1, with a projection head to a shared dimension (start at 256).
- Text tower: `all-MiniLM-L6-v2` (already familiar from ListingLens), projection head to the same dimension. Start frozen, then unfreeze the top layers in a second run and compare.
- InfoNCE with in-batch negatives, learnable temperature initialized around 0.07. L2-normalize both sides.

**Critical detail — batch size and negatives.** Contrastive learning draws its negatives from the batch, so a small batch means weak training signal, and gradient accumulation does **not** fix this (it accumulates gradients, not negatives). If GPU memory forces a batch below ~128, implement a MoCo-style memory queue of recent embeddings instead of just shrinking the batch. Decide this early; it changes the training loop structure.

**Second run:** hard negative mining — sample negatives preferentially from the same `product_type`, so the model learns fine-grained distinctions rather than "shoe vs sofa."

**Evaluation harness (`python -m eval.run_retrieval`), producing a dated markdown report the same way ListingLens does:**

Metrics: Recall@1, Recall@10, Recall@50, NDCG@10, MRR.

Baselines, all four required:
- Random ranking (sanity floor)
- Popularity / class-prior ranking
- BM25 over titles (text-only strong baseline)
- Frozen CLIP ViT-B/32 zero-shot (the "did fine-tuning actually help" baseline)

**If the fine-tuned model loses to frozen CLIP, report it.** That is a real and publishable result at this catalog size, and the honest reporting is worth more than a quiet omission. Your ListingLens README already does this well; keep the habit.

**Acceptance:** eval report committed, metrics table in README with all four baselines, retrieval demo runnable from CLI.

---

### M3 — Spark embedding job, index, and service (~1 week)

**Spark job** (`scripts/embed_catalog.py`): batch-embed the full catalog with the trained image tower, write `embeddings.parquet` partitioned sensibly. This is what carries the PySpark credential forward once the trading project is retired, so it needs to be genuine Spark, not pandas in a Spark wrapper.

**Index:** build FAISS over the catalog embeddings. Compare `IndexFlatIP` against `IndexIVFPQ` at two or three `nlist`/`nprobe` settings and **report the recall-versus-latency tradeoff as a table.** "I chose IVF-PQ and here is what it cost me in recall" is a much stronger interview answer than "I used FAISS."

**Query-time inference:** export the image encoder to ONNX and quantize it. You already run MiniLM through ONNX Runtime in ListingLens, so this is a known pattern. Measure and record the latency and accuracy delta from quantization.

**Service:** FastAPI with the four endpoints above, Dockerfile, docker-compose. Benchmark p50/p95/p99 at a stated concurrency and put the numbers in the README. Include the index-build step in CI as a smoke test on a tiny subset.

**Acceptance:** service runs from `docker compose up`, latency numbers recorded, index tradeoff table in README.

---

### M4 — ListingLens integration (~3-5 days)

This is the PR into the existing repo.

**Add `backend/mcp_server/tools/visual_competitor_search.py`:**
- Thin HTTP client to the retrieval service, with an explicit timeout.
- **Graceful degradation**, matching the existing `resilient_call` philosophy: on timeout, connection error, or 5xx, fall back to the current synthetic `competitor_search` and label the result as degraded. The agent should never fail a run because the retrieval service is cold-starting.
- MCP wrapper alongside the existing five tools.

**Planner prompt update:** teach it when a visual comparison is the right tool versus the text competitor lookup. Keep the change minimal and localized.

**Eval, and this is the part that matters:**
- Add gold-set queries that should exercise the new tool ("what products look like mine and are cheaper", "who else sells something in this style").
- Re-run the full 33-query eval plus the new rows. Report trajectory precision, recall, F1 before and after.
- **Remember your own noise floor finding.** Two runs of identical code disagreed on 11 of 24 rows. A single-run delta on trajectory metrics is not evidence. Run it repeatedly, or report the per-type tool-selection count as the primary signal rather than the aggregate.

**Frontend:** surface retrieved product thumbnails in the trace panel when the tool fires. Small change, large demo impact.

**Acceptance:** eval report showing before/after with an honest read, including a regression if there is one. Live demo shows the tool firing with real images.

---

### M5 — Re-ranker, optional (~1 week)

LightGBM ranker over the top-K retrieved candidates, using embedding similarity, price, rating, brand match, and category match as features. Report NDCG@10 improvement over pure retrieval.

Plus `docs/ab_test_design.md`: how an online test of this ranker would be structured — unit of randomization, primary metric, guardrail metrics, minimum detectable effect, stopping rule. A design document, explicitly labeled as a design and not a result.

---

## 3. Technical decisions to pin before starting

| Decision | Default | Revisit if |
|---|---|---|
| Image resolution | 224x224 | ViT variant needs otherwise |
| Shared embedding dim | 256 | Recall plateaus low |
| Contrastive batch size | 256 | GPU memory forces smaller, then add memory queue |
| Temperature | Learnable, init 0.07 | Training unstable |
| Text tower | MiniLM frozen first, then top-2 layers unfrozen | Text-only baseline beats the joint model |
| Index type | Flat first, IVF-PQ second | Catalog under 50K makes flat fine at serving latency |

---

## 4. Known traps

- **Splitting by image instead of product** silently inflates every retrieval number. Test for it.
- **Multilingual titles** in ABO will quietly poison the text tower. Filter early.
- **Gradient accumulation does not add contrastive negatives.** If the batch is small, use a memory queue.
- **The index should contain the full catalog**, including test-split items; the held-out part is the *queries*, not the indexed corpus. Be explicit about this in the eval code or reviewers will assume the wrong thing.
- **Don't deploy the training-time encoder.** ONNX-export and quantize for serving, keep PyTorch for training only.
- **Cold starts** on free-tier hosting will dominate your p99. Measure warm and cold separately and say which is which.

---

## 5. Working with Claude Code on this

- **One milestone per session.** These are sized so that each fits in a session without context thrashing.
- **Ask for a plan before code** at the start of each milestone, then approve or correct it. Cheaper than reviewing 800 lines after the fact.
- **Write a `CLAUDE.md`** in the new repo covering: the milestone structure, the "baselines are mandatory" rule, the no-committed-data rule, the split-by-product rule, and the honest-reporting convention. It will drift without it.
- **Require a test with every data-transform commit.** The leakage traps above are exactly the kind that pass code review and ruin results.
- **Keep the eval harness a first-class module from M2 onward**, not something bolted on at the end. Your ListingLens experience already proved this: the eval is the dev loop.

---

## 6. What this produces for the resume

After M3, one project line covering: fine-tuned vision encoder in PyTorch with reported baselines, two-tower contrastive retrieval with Recall@K and NDCG against four baselines, PySpark batch embedding over ~147K products, FAISS index with a documented recall/latency tradeoff, ONNX-quantized serving with p99 latency.

After M4, an additional clause on the ListingLens line: replaced a synthetic tool with a real retrieval service, with before/after agent trajectory metrics.

That is the computer vision gap, the PyTorch training gap, the personalization gap, and the scale gap, closed and visible on the page.
