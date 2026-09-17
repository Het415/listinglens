# ListingLens — Session Handoff (2026-05-18, Cursor / Opus 4.7)

> Pickup context for the next chat. Self-contained — you don't need to read any other handoff doc to continue.

---

## TL;DR

ListingLens is a deployed agentic Amazon-review analysis platform with three frontend surfaces (`/dashboard`, `/dashboard/reviews`, `/assistant`) and a FastAPI backend on Render. **This session migrated the canonical URL to a custom domain, fixed a silently-broken eval judge, and shipped two queued UX features (dashboard-card → assistant deep-links, demo-mode banner).** Everything is deployed and live.

**The next pickup is queued item #8: auto-populate Competitor Compare from `competitor_search`.** Concrete starting points are at the bottom of this doc — there's a non-trivial design decision to surface to the user before coding (mock competitor ASINs aren't in the analyzed catalog, so naive pre-fill of the existing Compare slots won't work).

---

## Live URLs

- **Frontend (canonical):** https://listinglens.hetprajapati.me
- **Frontend (Vercel default, kept as fallback):** https://listinglens-kappa.vercel.app
- **Backend API (Render):** https://listinglens-api.onrender.com
- **GitHub repo:** https://github.com/Het415/listinglens
- **Branch:** `main` (PRs auto-deploy; direct pushes also auto-deploy)

---

## Repo / local setup

- **Repo root:** `/Users/hetprajapati/github/listinglens`
- **Python venv:** `.venv/` at repo root, Python 3.13. Has `langgraph`, `mcp`, `instructor`, `anthropic`, `xgboost`, `faiss`, `onnxruntime` installed (all needed for the eval to run end-to-end). Note the existing `.venv` still carries torch/sentence-transformers from before the ONNX migration — harmless, but a rebuild drops ~2GB.
  - ⚠️ The existing `.venv` is **not** a clean venv: its `bin/python` is a symlink to `/opt/anaconda3/bin/python`, and `pyvenv.cfg` still records a creation path of `/Users/hetprajapati/listinglens/.venv` (the repo has since moved under `github/`). That is how local drifted away from production in the first place. Prefer rebuilding it as a real, project-owned 3.13 environment — see "Useful local commands".
- **`.env`** at repo root has `GROQ_API_KEY` and `HUGGINGFACE_API_KEY` set (eval reads these via `load_dotenv(override=True)` to outrace Claude Code's parent-shell key shadowing).
  - ⚠️ **`ANTHROPIC_API_KEY` is NOT in `.env`** — verified 2026-09-17. This file previously claimed it was. Consequence: the LLM-as-judge cannot run. `eval/run_eval.py` preflights the key and exits 1 with instructions, so judged runs fail fast rather than scoring zeros — but it means **no eval has been judged since 2026-05-18**. The 2026-09-15 post-fix run was `--no-judge`; its header claimed a judge model because the report advertised one unconditionally (since fixed). Add the key to `.env` before quoting any judge metric.
- **Frontend:** `frontend/` — Next.js 16, React 19, Tailwind v4. `node_modules` may be sparse in some environments; run `npm install` if needed.
- **Frontend env (production):** Vercel must have `NEXT_PUBLIC_API_URL=https://listinglens-api.onrender.com`. The `frontend/.env.example` and `frontend/.env.local` files in the repo are stale (point at a deprecated Railway URL) — do NOT trust them.

---

## Inherited context (one paragraph)

A prior Claude Code session (`HANDOFF.md` on the unmerged `origin/docs/session-handoff` branch) shipped: a unified `/assistant` page with manual Quick-Q&A vs Copilot mode toggle backed by `POST /assistant/query`; per-ASIN sessionStorage chat history; mobile trace dropdown; removal of the Settings page; deploy-fix that folded `langgraph`/`mcp`/`instructor` into the main `requirements.txt` (the agent layer had been silently uninstalled in production for weeks but nobody noticed because the live `/agent` page used a mock fallback); CORS allowlist update for the new custom domain. That session ended with the CORS fix merged but not yet redeployed by Render — **that has since deployed and the custom domain works end-to-end.** All work from that session is on `main`.

If you ever need the full 346-line prior handoff, it's at:
```
git show origin/docs/session-handoff:HANDOFF.md
```

---

## What this session shipped (commit-by-commit, most recent first)

### `3fb44b43` — `feat(onboarding): demo-mode banner + extract DEMO_ASIN constant`

First-time visitors landing on `/dashboard` or `/dashboard/reviews` without `?asin=` silently saw the TOZO T10 demo with no indication it wasn't their own product. Three files (`dashboard/page.tsx`, `dashboard/reviews/page.tsx`, `assistant/page.tsx`) all hardcoded `'B08XPWDSWW'` as the fallback — drift waiting to happen.

- New `frontend/lib/demo-config.ts` exports `DEMO_ASIN` and `DEMO_PRODUCT_NAME` as the single source of truth.
- New `frontend/components/dashboard/demo-mode-banner.tsx` — dismissible per-tab via sessionStorage (key `demo_banner_dismissed`), explicitly names the demo product, has a primary "Analyze your own product" CTA linking to `/`. Hydrate-then-render avoids a flash of un-dismissed state. Try/catch on sessionStorage degrades gracefully in private-mode browsers.
- Banner mounts in `/dashboard/page.tsx` and `/dashboard/reviews/page.tsx` only when `!searchParams.get('asin')`. Once the user analyzes a real product, `?asin=…` is set, `isDemo` flips to false, banner disappears for the rest of the session without needing dismissal.

### `2d8dde33` — `feat(dashboard): wire Topic Analysis + Quality Breakdown cards into /assistant`

Each dashboard card surfaced a problem (worst review topic, return-risk drivers) but had no action — users had to context-switch into `/assistant` and re-type the question themselves.

- Added an inline "Ask Copilot how to fix this" link to the `TopicAnalysis` card's amber insight callout. Only renders when the top topic is actually a complaint (`negative > positive`); a card showing only positive themes correctly stays clean. The deep-link names the specific topic so the agent gets concrete context.
- Added a full-width "Ask the Copilot to expand on these" CTA below the AI Recommendations sub-card in `QualityBreakdown`. Pre-fills a question that uses live `risk_label`/`risk_pct` when present (`"My listing's return risk is HIGH at 41%. Walk me through..."`), generic fallback otherwise.
- `/assistant` now reads `q` and `mode` from URL params and auto-submits exactly once per unique `q` (tracked in a ref). After submit, `q`/`mode` are stripped via `router.replace` so back-button doesn't replay. Each new deep-link fires because the value changes, not because the param is present.
- **Subtle bug fixed during implementation:** within-`/assistant` client-side nav (e.g. clicking a second deep-link from the dashboard while already on `/assistant`) doesn't re-init `useState`. `setMode(prefillMode)` is async; `submit(prefillQuery)` runs immediately with stale `mode` in closure. Fix: `submit()` now accepts an optional `overrideMode` parameter that the auto-submit effect always passes.

### `85597427` — `fix(eval): bump default judge to Haiku 4.5`

`eval/judges.py` defaulted to `claude-3-haiku-20240307` (the original Haiku 3 from March 2024). Anthropic retired that model — every API call returns 404. Worse, the error is caught per-call and stored as `score=None`, so eval runs complete normally but the report's judges block comes out N/A across all 4 dimensions. Stage 4's published numbers from 2026-05-16 used this model and may have actually been broken (or the retirement happened more recently and the prior run hit the API right before deprecation).

`eval/run_eval.py:_judge_label()` already advertised `claude-haiku-4-5-20251001` in the report header, so even before the 404 there was a label/runtime mismatch. Bumping the `judges.py` default to Haiku 4.5 fixes both bugs in one change.

### `f86cf12b` — `chore(domain): point hardcoded URLs at listinglens.hetprajapati.me`

User migrated the canonical URL to a custom domain. Updated the in-repo references that were still pointing at the old `listinglens-kappa.vercel.app`:
- `frontend/lib/exportReport.ts:146` (PDF report footer)
- `app.py` CORS regex broadened from `https://.*\.vercel\.app` → `https://([a-z0-9-]+\.)*(vercel\.app|hetprajapati\.me)` so any future `*.hetprajapati.me` subdomain works without env changes
- `README.md` (badge + 4 demo links)
- `ARCHITECTURE.md` (one v1 `/chat` link)

The CORS regex uses Starlette's `fullmatch`, which means `https://malicioushetprajapati.me` won't match (no `.` separator).

---

## Eval state — what's measured, what's stale

**Most recent full 30-query agent run:** `eval/reports/2026-05-17-full-resume.md`
- **30/30 success, 0 errors** (Stage 4 had 10% errors from Groq quota hits)
- **Trajectory F1 = 0.800** (Stage 4: 0.85; ±5pp is normal stochastic noise on Groq)
- **Decision accuracy = 60.0%** (Stage 4: 56.7%)
- **Latency p50/p95 = 18.6s / 34.1s** (Stage 4: 18.2s / 34.5s — flat)
- **Judges: ALL `null`** because of the retired-Haiku-3 bug that's now fixed in `85597427`. Re-run will produce real scores.

**Why we couldn't re-run:** Groq daily TPD cap (500k tokens) hit during the second attempt. The first run + leftover-from-earlier-day usage exceeded the limit. Cap resets at UTC midnight = **8 PM EDT**. After reset, one command:

```bash
.venv/bin/python -m eval.run_eval --output-tag full-judged
```

…produces `eval/reports/2026-05-XX-full-judged.md` with Haiku 4.5 judge scores across all 4 dimensions, comparable to Stage 4's `dec=0.431, ev=0.444, hal=0.737, comp=0.759`.

**Persistent agent weakness this run reconfirmed:** launch queries are 3/10 correct. Agent over-confidently picks `go` on 7/10 launch queries when gold says `needs_more_data` or `no_go`. This is queued item #7 (Planner prompt tuning) — depends on having clean judge scores to iterate against, which is why item #8 is being picked up first.

---

## What's queued (handoff-prioritized order)

| # | Item | Status |
|---|---|---|
| 1 | Wire dashboard cards → `/assistant` | ✅ done (`2d8dde33`) |
| 2 | Onboarding banner for first-time sellers | ✅ done (`3fb44b43`) |
| 3 | Delete or build out `/dashboard/visual` placeholder | open |
| 4 | Surface real backend error messages on dashboard fetch failures | open |
| 5 | Unify loading states across `/dashboard/*` (spinner vs skeleton vs third style) | open |
| 6 | Mobile QA pass on `/dashboard/*` (we did `/assistant` last session) | open |
| 7 | Planner prompt tuning to fix launch-query over-confidence | open (waiting for fresh judge scores) |
| **8** | **Auto-populate Competitor Compare from `competitor_search`** | **next pickup** |
| 9 | Record the Loom demo (originally Stage 6) | open |

---

## ★ Next pickup — Item #8: Competitor Compare auto-populate

**Goal:** when the user is viewing a dashboard for ASIN X, give them a one-click path to "compare X against its top competitors" using the existing `competitor_search` MCP tool.

### Files involved

- **Compare page (UI):** `frontend/app/dashboard/compare/page.tsx`. Currently has 3 manual `ProductSlot` inputs and a `Compare` button. Drives via `/analyze/<asin>` for each selected ASIN.
- **Competitor search tool:** `backend/mcp_server/tools/competitor.py` — function `competitor_search(asin: str, max_results: int = 5) -> dict`. Note the file is named `competitor.py`, not `competitor_search.py` (prior handoff was off by one).
- **Mock market data:** `backend/data/mock_market_data.json` — seeded competitors for all 12 supported ASINs (`competitors` key) plus an `asin_to_category` map.
- **Sidebar nav:** `frontend/components/sidebar.tsx` — has a "Compare" entry.
- **Dashboard page:** `frontend/app/dashboard/page.tsx` — knows current product's ASIN; could host a "Compare against competitors" button.

### Design decision the user needs to make first

There's a **constraint** the prior handoff didn't flag:

The competitor ASINs returned by `competitor_search` are **mock data** seeded for narrative purposes. They are NOT in the supported catalog — `/analyze/<competitor_asin>` will 404 for them.

For example, `competitor_search("B08XPWDSWW")` returns competitors:
- `B098P3JV63` — Anker Soundcore Liberty 4 NC
- `B0BS1PRC4M` — JBL Tune Buds True Wireless
- `B0CN2GMSLT` — Soundcore P40i
- `B0BDHB9Y8H` — TOZO A1 Mini

…none of which the backend can `/analyze`. The Compare page's whole flow is built on `/analyze/<asin>` returning real review/risk data per ASIN.

So naively pre-filling the existing `ProductSlot` inputs with competitor ASINs and clicking Compare will fail with "ASIN X not found in cached results."

### Three viable design paths — surface this to the user

**Option A — In-catalog peers only.** Pre-fill Compare slots with up to 2 *supported* ASINs from the same category (using `asin_to_category` map). Real `/analyze` data on both sides; the existing Compare metrics work unmodified. Limitation: most categories have only 1-2 supported peers, so "top 3 competitors" promise is downgraded to "1-2 in-catalog peers".

**Option B — Add a "Market context" panel below the existing 1:1 compare.** Don't touch the manual ASIN slots. New panel shows the `competitor_search` mock data as read-only cards (title, brand, price, rating, top features, top complaints) — explicitly labeled "Market reference (synthetic data)". Honest about the mock-data limitation. Lighter integration: no changes to the Compare metric pipeline.

**Option C — Hybrid.** Pre-fill in-catalog peers in slots (Option A), AND show synthetic competitors as info-only cards below (Option B). Most complete but most code.

**Recommendation:** Open with Option B because (a) it's the smallest scope that delivers user value, (b) it's honest about the data being mock, (c) it doesn't change the existing Compare flow which works. Then upgrade to Option C only if the user wants in-catalog peers pre-filled too.

### Concrete starting code (whichever option)

1. Decide whether to add a new backend endpoint `GET /competitors/{asin}` that wraps the tool, or just call `POST /agent/query` with a query like "find competitors for this product" and parse the streamed `tool_result`. The endpoint is much simpler — recommended.
2. New endpoint in `app.py`:
   ```python
   @app.get("/competitors/{asin}")
   def get_competitors(asin: str, max_results: int = 5):
       try:
           from backend.mcp_server.tools.competitor import competitor_search
           return competitor_search(asin, max_results=max_results)
       except ValueError as e:
           raise HTTPException(status_code=404, detail=str(e))
   ```
3. Frontend hook in `frontend/app/dashboard/compare/page.tsx` — read `?asin=` from URL, call `/competitors/{asin}` on mount, render the chosen UI.
4. Add a "Compare against competitors" button to the dashboard's score-cards row OR to the topbar that links to `/dashboard/compare?asin=…`.

### Sanity check before merging

- **CORS:** new endpoint must work from the custom domain. Current regex in `app.py` already covers it; no changes needed.
- **Mock data labeling:** if you go with Option B/C, the UI MUST visually distinguish synthetic competitor cards from real `/analyze` cards. Past UI honesty was important to the user (it's why the prior handoff explicitly explains the rule-based classifier was scrapped — they preferred honest UX over hidden behavior).

---

## Critical gotchas (carry-over from earlier handoff, still apply)

1. **`ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` shadowing.** Claude Code's parent shell exports its own keys that override `.env`. Any script that hits Anthropic needs `load_dotenv(override=True)` AND `os.environ.pop('ANTHROPIC_BASE_URL', None)`. Already wired into `eval/run_eval.py`. Cursor's shell doesn't have this issue but the eval guard is harmless to keep.
2. **Groq free-tier limits are now 8000 TPM / 1000 RPD PER MODEL**, not a single org-wide 500k TPD pool (the older note below reflects the previous scheme). Per-model buckets are why the stage split in [src/llm_config.py](src/llm_config.py) works: the planner, executor and review_qa paths draw on three independent limits. `python -m scripts.doctor` prints the bucket map and warns when two concurrent stages share one.
3. **`min-h-screen` on layouts causes page-level scroll** when content is taller than viewport. Use `h-screen overflow-hidden` instead. Affects `/agent/layout.tsx`, `/chat/layout.tsx`, `/assistant/layout.tsx`.
4. **Groq decommissioned the entire Llama family (Sept 2026).** Both `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` now 404 with `model_not_found`, which broke every LLM path — and looked like "retrieval is broken" because the RAG chain 404s *after* retrieval succeeds. All model IDs now live in [src/llm_config.py](src/llm_config.py). Run `python -m scripts.doctor` to validate every pin against Groq's live catalog; it exits non-zero and names the env var to change.
5. **`/agent/query/mock` always streams the same canned TOZO returns scenario** regardless of input — by design, a development fixture. Live endpoint is `/agent/query`. The new `/assistant` page always calls live `/assistant/query`.
6. **Frontend uses `fetch` + `ReadableStream` for SSE**, not `EventSource`. Shared reader at `frontend/components/assistant/sse.ts`.
7. **`frontend/.env.local` is tracked-but-gitignored** (committed before gitignore). Local changes should NOT be committed (`git restore --staged` first). Production env lives in Vercel dashboard, not this file.
8. ~~**macOS dev:** `torch==2.1.0+cpu` is Linux-only, install plain `torch`.~~ **Moot — torch is no longer a dependency.** Embeddings run on onnxruntime (`src/onnx_embeddings.py`), so there is no torch pin, no `--extra-index-url`, and no platform-specific install step: `pip install -r requirements.txt` just works everywhere. `brew install libomp` for XGBoost still applies. New floor to know about: faiss-cpu >=1.13 ships `macosx_14_0_arm64` wheels only, so local dev needs macOS 14+.
9. **Sync function calls inside async SSE generators block the event loop.** In `/assistant/query`, `await asyncio.to_thread(review_qa, ...)` for the quick path. `loop.run_in_executor` deadlocked on FAISS init — `asyncio.to_thread` works.
10. **`.claude/worktrees/`** in repo root is internal Cursor / Claude Code worktree state. Always untracked. Don't `git add` it.
11. **Sandbox + OpenMP — status: could not reproduce, cause still unproven.** Historically, importing `xgboost`/`faiss`/`torch` inside Cursor's default sandbox failed with `OMP Error #179: SHM2 failed`, and a local uvicorn died with SIGSEGV (exit 139) after one request. Re-tested on the aligned 3.13 stack (torch 2.6.0, faiss-cpu 1.15.0, xgboost 3.4.1): importing and *exercising* all three in one sandboxed process succeeded, with no `KMP_DUPLICATE_LIB_OK` escape hatch — in both a clean venv and the anaconda-symlinked `.venv`.
    Do **not** read that as fixed, but the hazard did shrink. Dropping torch removed one of the three bundled OpenMP runtimes — `faiss/.dylibs/libomp.dylib` and `sklearn/.dylibs/libomp.dylib` remain (torch/lib/libomp.dylib is gone), and anaconda still adds `libomp.dylib` *and* `libiomp5.dylib` in `/opt/anaconda3/lib`. Duplicate-OpenMP crashes are load-order dependent, so they come and go. The dependency alignment plausibly helped by making the wheel set self-consistent, but nothing here proves causation. If it resurfaces, the first move is to stop using the anaconda-symlinked interpreter (see "Repo / local setup"), which is the only source of the *second* OpenMP vendor.
12. ✅ **RESOLVED (verified 2026-09-17) — Groq removed the entire Llama family.**
    A fix now exists in the **main checkout, uncommitted**: new `src/llm_config.py`
    (single source of truth, per-stage fallback chains, `resilient_call` failing over on
    404/429) and `scripts/doctor.py` (preflight). All 11 former hardcoded call sites import
    from it; `render.yaml` carries all four env vars. Verified independently: every model ID
    is present in Groq's live catalog (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`,
    `openai/gpt-oss-safeguard-20b`, `qwen/qwen3.8-27b`), `python -m scripts.doctor` passes
    all checks, and the post-fix eval ran 8/8 with a **0% error rate** (down from 33%).
    Quality held: restricted to launch-type queries for a like-for-like comparison,
    3/8 (38%) decision accuracy vs 4/10 (40%) before, trajectory F1 0.888 vs 0.900 — noise
    at that sample size. **Still needs committing and a redeploy.** Original report follows.

    🔴 **Groq removed the entire Llama family — production Copilot was broken.**
    Confirmed live on 2026-09-15 against `listinglens-api.onrender.com`:
    `NotFoundError: 404 - The model 'llama-3.3-70b-versatile' does not exist or you do not
    have access to it.` Both `llama-3.3-70b-versatile` (AGENT_MODEL / GROQ_MODEL) and
    `llama-3.1-8b-instant` (EXECUTOR_MODEL / INTENT_LLM_MODEL) are gone. This is unrelated
    to the dependency/memory work and was not introduced by it. Retrieval is unaffected —
    the SSE stream reaches `tool_call review_qa` and only fails at the LLM call, which is
    why it presents misleadingly as "retrieval is broken".

    Known-good replacements (free Groq models supporting **both** tool-calling and
    structured output, as of 2026-09-15): `openai/gpt-oss-120b`, `openai/gpt-oss-20b`,
    `openai/gpt-oss-safeguard-20b`, `qwen/qwen3.8-27b`. Avoid `allam-2-7b` and the
    `groq/compound*` models — they reject a `tools` payload outright.

    The model name is hardcoded as an env-var *default* in **11** places, which is why each
    decommission is this painful:
    `render.yaml:33,38` · `src/rag_chatbot.py:29` · `src/intent_classifier.py:88` ·
    `backend/brief/generate.py:21` · `backend/agent/nodes/{planner.py:17,
    synthesizer.py:18, executor.py:28}` · `eval/run_eval.py:219` · `eval/baselines.py:35` ·
    `scripts/generate_transcripts.py:42`.

    ⚠️ A centralised `src/llm_config.py` and a `scripts/doctor.py` preflight are referenced
    in session notes as the fix, but **neither exists on any branch in this repo** as of
    this handoff (checked `git ls-tree` across all refs). They appear to be in flight in a
    concurrent session. Don't assume they are there; if they land, this gotcha collapses to
    a one-line change and `python -m scripts.doctor` becomes the first thing to run.
13. **`deepeval` loads `.env` before `conftest.py` runs — it silently flipped the test
    suite into development mode.** Diagnosed 2026-09-17. `deepeval` registers a `pytest11`
    entry point, so pytest imports it *before* `tests/conftest.py`. That import calls
    `load_dotenv()`, which sets `ENV_MODE=development` from the local `.env`. conftest's
    `os.environ.setdefault("ENV_MODE", "production")` is then a **no-op**, because the value
    is already present.

    Consequence: `run_full_pipeline` skipped its production 404 guardrail, fell through to
    the heavy NLP branch, and tried a real HuggingFace download for the deliberately-bogus
    ASIN `B000000000` — turning two 404 assertions into 500s and stretching the suite from
    ~2s to **356s**. Local-only: CI exports `ENV_MODE=production` and has no `.env`.

    Proven pre-existing — reproduces on a pristine `git archive HEAD` export with no Groq
    changes present, so the Groq work did not cause it.

    Fixed in the `nifty-dirac-84511f` worktree (uncommitted) by assigning
    `os.environ["ENV_MODE"] = "production"` unconditionally plus an autouse fixture that
    pins `app.ENV_MODE` and asserts it. Verified: **7 passed in 2.08s** with `.env` present
    and deepeval installed.

    ⚠️ That fix's docstring states ".env was never the culprit — only a pre-existing
    environment variable could beat setdefault." **That is incorrect.** The shell had
    `ENV_MODE` unset; the value came from `.env`. `load_dotenv(override=False)` only yields
    to variables *already in* `os.environ`, and at plugin-import time ENV_MODE is not yet
    set — conftest hasn't run. Demonstrated A/B: same directory, `import deepeval` gives
    `'development'` with `.env` present and `None` with it removed. The fix is right; the
    stated cause is not, and will mislead whoever reads it next.
14. **CI never ran.** `.github/workflows/eval-on-pr.yml` exists but path filter only watches `backend/**`, `eval/**`, `requirements-agent.txt`, `src/rag_chatbot.py`, `src/fusion.py` — and triggers only on `pull_request`. No PR has matched (most touched `app.py` at root or frontend). Direct pushes don't trigger either. Total Actions runs to date: 0. Worth widening filter + adding `workflow_dispatch` trigger as a one-line follow-up.

---

## Runtime & dependency alignment (2026-09-15)

**The problem.** The environment tested locally was not the one production installed.
`requirements.txt` pinned `sentence-transformers==2.7.0` / `transformers==4.44.2` /
`torch==2.1.0+cpu` on Python 3.11; the local `.venv` had resolved 5.3.0 / 5.3.0 / 2.6.0
on Python 3.13. Both "worked", so the gap stayed invisible.

**What was actually wrong** — worth recording, because the obvious diagnosis is wrong:

- `langchain-huggingface==1.2.1` does **not** hard-require `sentence-transformers>=5.2`
  and `transformers>=5.0`. Those floors live behind its `full` **extra**. Plain
  `langchain-huggingface` declares only `huggingface-hub`, `langchain-core`, and
  `tokenizers`. So pip never reported a conflict, and the old pin set resolved cleanly
  on linux/py3.11 — it just installed a stack two majors below what upstream tests.
  This was a silent-runtime-divergence bug, not a resolver failure.
- The pin that genuinely could not work was `torch==2.1.0+cpu`: the `+cpu` local version
  is published only for `linux_x86_64` / `win_amd64`, and only for cp38–cp311. On an
  arm64 Mac — or on *any* platform at 3.13 — `pip install -r requirements.txt` was
  unsatisfiable. That is why the local venv was built by other means and drifted.
- `numpy>=1.26,<2.0` was a third, unreported divergence: local had numpy 2.4.3.

**The fix.** Align forward rather than back. `langchain-huggingface[full]==1.2.1` is now
requested explicitly, which converts the sentence-transformers/transformers floors from a
comment into a constraint the resolver enforces. torch is selected by environment marker.
numpy moves to `>=2.1,<3`.

**Python version: moved to 3.13 everywhere** (`.python-version`, `Dockerfile`,
`ci.yml`, `eval-on-pr.yml`) rather than pulling local back to 3.11.

- The whole stack ships cp313 wheels (torch 2.6, transformers 5.3, sentence-transformers
  5.3, faiss-cpu ≥1.13, numpy 2.5, pandas 3, xgboost 3.4). Nothing forced 3.11.
- 3.11 is in security-only maintenance; there is no 3.11 interpreter on the dev machine
  at all (only system 3.9 and brew 3.14), so "align local to 3.11" meant installing one
  purely to satisfy a stale file.
- `.python-version` holds `3.13`, not a pinned patch. Render explicitly supports the
  major.minor form and resolves the latest patch, which is the same thing
  `python:3.13-slim` does — so the two surfaces can no longer disagree on patch level,
  which is the failure mode being fixed. The cp313 ABI is what actually governs wheel
  compatibility, and that is pinned.

**Verification performed.** A clean 3.13 venv built from the new `requirements.txt`
(`uv pip check`: 131 packages, all compatible; `pytest tests/`: 7 passed):

- All **12** committed FAISS indexes in `data/processed/vectorstore_*/` load, every one
  at `d == 384`; `B08XPWDSWW` reports `ntotal == 2883` as expected.
- Embedding-space fidelity was checked properly rather than by eyeballing search results:
  document vectors were pulled straight out of each index with `index.reconstruct(pos)`
  and compared against a re-embedding of the same source text under the new stack.
  **Worst cosine across all 12 stores: 1.000000.** MiniLM output is bit-identical, so the
  indexes do **not** need rebuilding and similarity search has not silently degraded.
- `requirements.txt`, `requirements-dev.txt`, and `requirements.txt + requirements-agent.txt`
  each resolve cleanly for linux-x86_64/cp313, the Render and Docker target. linux-arm64
  resolves too, which it could not before — see the note in `docker-compose.yml`.

**One new constraint to know about:** the `faiss-cpu>=1.13` floor (needed for cp313 wheels)
ships `macosx_14_0_arm64` wheels only, so local dev now requires **macOS 14 or newer**.
This machine is on 26.6.2, so it is a non-issue here; it would bite a collaborator on an
older macOS. Linux is unaffected.

**Docker image: built and exercised on the production target.**
`docker build --platform linux/amd64 -t listinglens-api:ci-amd64 .` succeeds. Inside the
image: `x86_64`, Python `3.13.15`, torch `2.6.0+cpu`, transformers `5.3.0`,
sentence-transformers `5.3.0`, faiss-cpu `1.15.0`, numpy `2.5.3`. The pip layer takes
~127s and every wheel resolves as a `cp313` / `manylinux_2_28_x86_64` binary — no source
builds. Image size **3.59GB** (uncompressed, `docker image ls`).

> Measurement note: `docker image inspect --format '{{.Size}}'` reports ~997MB for this
> image under OrbStack — that is the *compressed* figure and is not comparable to
> `docker image ls`. Use `docker image ls` when quoting image size.

- All 12 FAISS vectorstores re-verified *inside* the x86_64 image, worst cosine
  **1.000000**. Since the indexes were originally built on arm64 macOS, this also shows
  MiniLM output is bit-identical across architectures.
- Container boots, `/health` responds in ~4s, Docker HEALTHCHECK reaches `healthy`.
### A/B against the pre-change stack

The old `requirements.txt` + `python:3.11-slim` Dockerfile were rebuilt from `HEAD` into
`listinglens-api:pre-change` (same source tree, same data — the dependency stack is the
only variable). Two results worth recording, one of which contradicts a guess made
earlier in this work:

- **The old stack was not broken at runtime.** `langchain-huggingface==1.2.1` running
  against `sentence-transformers==2.7.0` loaded FAISS and completed retrieval without
  error. The suspicion that requesting the `full` extra was covering a live runtime break
  was wrong. `HuggingFaceEmbeddings` only touches `SentenceTransformer(...)` and
  `.encode(...)`, which are stable across 2.x and 5.x. So the `[full]` pin is a
  *drift-prevention* measure, not a bug fix — it keeps the stack from silently sliding
  apart again, which is still worth having.
- **The new stack is lighter, not heavier.** Measured identically on both images:

  | | idle | after `/analyze` | 1st vectorstore | 2nd | 3rd | image |
  |---|---|---|---|---|---|---|
  | old (3.11 / torch 2.1 / ST 2.7) | 273 MiB | 485 MiB | **1.033 GiB** | 1.047 GiB | 1.065 GiB | 4.14 GB |
  | new (3.13 / torch 2.6 / ST 5.3) | 193 MiB | 306 MiB | **651 MiB** | 664 MiB | 686 MiB | 3.59 GB |

  ~37% less resident memory at the RAG path and ~0.55GB off the image. Most of the image
  saving is `nvidia` (454M→288M) and `xgboost` (228M→85M); torch itself grew slightly
  (690M→708M).

⚠️ **Memory was the real constraint here — now addressed.** See the ONNX section below.
Note the earlier guess that production "must have been OOMing all along" was **wrong**:
a live `/assistant/query` against `listinglens-api.onrender.com` completed retrieval fine
on the old 1.03GiB stack, so the live service has more headroom than the "512MB free-tier"
note in this file implies. Worth confirming the actual plan in the Render dashboard, since
several decisions here are justified by that number.

- The old SIGSEGV-after-one-request symptom did **not** reproduce: 6 consecutive
  `/assistant/query` calls that genuinely load FAISS + MiniLM in the uvicorn event loop
  (confirmed via `Loading cached vectorstore` in the logs), across two different ASINs,
  all returned 200 with `running=true exit=0 restarts=0` and no OpenMP or segfault
  signature in the logs. Run with a deliberately invalid `GROQ_API_KEY` so retrieval
  executes fully and only the LLM call fails — costs none of the free-tier daily budget.

**Known, pre-existing, unchanged:** `xgboost` pulls `nvidia-nccl-cu13` on linux-x86_64
(a hard dep of xgboost 3.x, not something torch is dragging in). It was present before
this change too. Constraining to `xgboost<3` would drop it, but that risks the trained
model artifact, so it was left alone.

---

## Embeddings moved off torch → ONNX Runtime (2026-09-15)

**Why.** Profiled inside the production image, the embedding path cost 705 MiB RSS — and
almost none of it was the model:

| stage | RSS | delta |
|---|---|---|
| interpreter | 16 MiB | |
| `+ numpy` | 41 MiB | +25 |
| `+ torch` | 253 MiB | **+212** |
| `+ transformers` | 281 MiB | +28 |
| `+ sentence_transformers` | 557 MiB | **+276** |
| `+ faiss` | 570 MiB | +13 |
| `+ MiniLM weights` | 656 MiB | +87 |
| `+ one embed_query` | 705 MiB | +49 |

~490 MiB was framework import overhead before a single weight was read. The model is
87 MiB. And `src/rag_chatbot.py::_get_embeddings` was the **only** runtime user of any of
it — intent classification is TF-IDF + LogisticRegression via joblib, nothing else imports
torch. Env tuning (`OMP_NUM_THREADS=1`, `MALLOC_ARENA_MAX=2`) moved the needle not at all;
the cost is the libraries, not thread arenas.

**What changed.** New `src/onnx_embeddings.py` runs the same checkpoint through
onnxruntime + tokenizers. all-MiniLM-L6-v2 is Transformer → mean-pool → L2-normalize, so
the reimplementation is six lines. `torch`, `transformers`, `sentence-transformers` and
`langchain-huggingface` are gone from `requirements.txt`; `onnxruntime`, `tokenizers` and
`huggingface-hub` are in. The model revision is **pinned** (`1110a243…`) because an
unpinned Hub re-export would change vectors with no signal.

**Results** (same image, same measurement method, hard `--memory` caps):

| | image | RSS after 1st vectorstore | OOM floor | 512MB free tier |
|---|---|---|---|---|
| torch stack | 3.59 GB | 651 MiB | 544–576 MB | **OOM-killed, exit 137** |
| ONNX stack | **2.48 GB** | **380 MiB** | **320–384 MB** | **runs, 380/512 MiB** |

> Size caveat: `docker image ls` read `778MB` for this image immediately after the build
> finished and `2.48GB` once it settled. The settled figure is the real one — site-packages
> alone is 1.3G (down from 2.2G). Take an image size reading a moment after the build, and
> cross-check it against `du` inside the container. Image is now dominated by `nvidia`
> (288M, an xgboost 3.x dependency), `pyarrow` (156M) and `scipy` (108M); `onnxruntime` is
> 67M. Dropping the torch stack removed ~1.1GB.

- All **12** FAISS indexes still reproduce at **cosine 1.000000** — both in a clean venv
  and inside the x86_64 image. No re-indexing. Max drift 1.19e-07 (float32 rounding).
- All 12 ASINs loaded into one process under a hard 512MB cap: survives, peaks 469.8 MiB.
  The torch build OOM-killed on the *first*.
- `tests/test_onnx_embeddings.py` (6 tests) locks the contract: dimension, L2 norm,
  batch-vs-single agreement, reproduction of committed index vectors, and an assertion
  that `torch` is absent from `sys.modules` after embedding. Full suite: 13 passed.

**Watch this.** `_CHAIN_CACHE` in `backend/mcp_server/tools/review_qa.py` is an unbounded
dict — one chain per ASIN, never evicted. At 512MB with all 12 loaded it peaked at
469.8 MiB, which fits but is not roomy. If ASIN count grows, that dict is the thing to
bound first.

**Trade-off accepted:** the pooling/normalisation is now ours to maintain rather than
sentence-transformers'. It is six lines, pinned to a model revision, and covered by a test
that fails loudly on drift — but it is a real maintenance surface, and a future MiniLM
variant with different pooling would need `_encode` updated to match.

---

## Useful local commands

```bash
# Activate venv
cd /Users/hetprajapati/github/listinglens
source .venv/bin/activate

# Rebuild it clean on 3.13 (recommended — drops the anaconda symlink, so the
# local interpreter is the same 3.13 ABI the Dockerfile and Render install for)
uv venv .venv --python 3.13
uv pip install -r requirements.txt -r requirements-dev.txt
# plain pip works too:
#   pip install --prefer-binary -r requirements.txt -r requirements-dev.txt

# Confirm the environment is internally consistent
uv pip check

# Local backend
uvicorn app:app --host 127.0.0.1 --port 8000 --log-level warning

# Local frontend
cd frontend && npm run dev   # http://localhost:3000

# Run agent from CLI
python -m backend.agent.run --asin B08XPWDSWW "Why are returns spiking?" --pretty

# Run eval (no judge — cost-free, ~3 min)
python -m eval.run_eval --limit 5 --no-judge --output-tag smoke

# Run full 30-query eval with Haiku 4.5 judge (~20 min, ~$0.30 in tokens)
python -m eval.run_eval --output-tag full

# Test the /assistant/query endpoint locally
curl -N -X POST http://127.0.0.1:8000/assistant/query \
  -H "Content-Type: application/json" \
  -d '{"asin":"B08XPWDSWW","query":"what do 1-star reviews say?","mode":"quick"}'

# Test the competitor_search tool from CLI (for #8)
python -m backend.mcp_server.tools.competitor B08XPWDSWW --max 3

# Verify production CORS for the custom domain
curl -sI -X OPTIONS https://listinglens-api.onrender.com/supported-asins \
  -H "Origin: https://listinglens.hetprajapati.me" \
  -H "Access-Control-Request-Method: GET" | grep -i access-control

# Production health
curl https://listinglens-api.onrender.com/health
```

---

## Commit log since previous handoff

```
3fb44b43 feat(onboarding): demo-mode banner + extract DEMO_ASIN constant
2d8dde33 feat(dashboard): wire Topic Analysis + Quality Breakdown cards into /assistant
85597427 fix(eval): bump default judge to Haiku 4.5
f86cf12b chore(domain): point hardcoded URLs at listinglens.hetprajapati.me
6921050c Merge pull request #5 from Het415/fix/cors-custom-domain   ← end of prior handoff
```

---

## How to start the next chat

> Read `HANDOFF.md` in the repo root. We just finished items #1 (dashboard → assistant deep-links) and #2 (demo-mode banner) from the queue. The next pickup is **item #8: Competitor Compare auto-populate**. The "Next pickup" section spells out the design constraint (mock competitor ASINs aren't in the analyzed catalog) and gives three options — Option B is the recommended starting point. Surface the design choice to me before coding. The eval re-run for clean judge scores can happen any time after 8 PM EDT (Groq quota reset); don't wait for it to start #8.

*End of handoff.*
