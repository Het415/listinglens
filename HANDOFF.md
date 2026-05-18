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
- **Python venv:** `.venv/` at repo root. Symlinks Python 3.13 (anaconda). Has `langgraph`, `mcp`, `instructor`, `anthropic`, `xgboost`, `faiss`, `sentence_transformers` installed (all needed for the eval to run end-to-end).
- **`.env`** at repo root has `GROQ_API_KEY`, `HUGGINGFACE_API_KEY`, `ANTHROPIC_API_KEY` set (eval reads these via `load_dotenv(override=True)` to outrace Claude Code's parent-shell key shadowing).
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
2. **Groq daily TPD cap is 500k tokens** on free tier. Resets at UTC midnight (8 PM EDT). Stage 4 hit it; this session's second eval attempt hit it. Plan eval re-runs accordingly.
3. **`min-h-screen` on layouts causes page-level scroll** when content is taller than viewport. Use `h-screen overflow-hidden` instead. Affects `/agent/layout.tsx`, `/chat/layout.tsx`, `/assistant/layout.tsx`.
4. **Llama 3.3 70B on Groq emits malformed `tool_calls`** on tool-heavy prompts. Agent uses `meta-llama/llama-4-scout-17b-16e-instruct` instead (`AGENT_MODEL` env var on Render pins this).
5. **`/agent/query/mock` always streams the same canned TOZO returns scenario** regardless of input — by design, a development fixture. Live endpoint is `/agent/query`. The new `/assistant` page always calls live `/assistant/query`.
6. **Frontend uses `fetch` + `ReadableStream` for SSE**, not `EventSource`. Shared reader at `frontend/components/assistant/sse.ts`.
7. **`frontend/.env.local` is tracked-but-gitignored** (committed before gitignore). Local changes should NOT be committed (`git restore --staged` first). Production env lives in Vercel dashboard, not this file.
8. **macOS dev:** `torch==2.1.0+cpu` from `requirements.txt` is Linux-only. Install plain `torch` from PyPI. `brew install libomp` for XGBoost.
9. **Sync function calls inside async SSE generators block the event loop.** In `/assistant/query`, `await asyncio.to_thread(review_qa, ...)` for the quick path. `loop.run_in_executor` deadlocked on FAISS init — `asyncio.to_thread` works.
10. **`.claude/worktrees/`** in repo root is internal Cursor / Claude Code worktree state. Always untracked. Don't `git add` it.
11. **Cursor sandbox + OpenMP.** Running anything that imports `xgboost`, `faiss`, or `torch` from inside Cursor's default sandbox fails with `OMP Error #179: SHM2 failed`. Either run shell with `required_permissions: ["all"]` or have the user run it in their own terminal. The eval falls into this category.
12. **CI never ran.** `.github/workflows/eval-on-pr.yml` exists but path filter only watches `backend/**`, `eval/**`, `requirements-agent.txt`, `src/rag_chatbot.py`, `src/fusion.py` — and triggers only on `pull_request`. No PR has matched (most touched `app.py` at root or frontend). Direct pushes don't trigger either. Total Actions runs to date: 0. Worth widening filter + adding `workflow_dispatch` trigger as a one-line follow-up.

---

## Useful local commands

```bash
# Activate venv (anaconda-symlinked Python 3.13)
cd /Users/hetprajapati/github/listinglens
source .venv/bin/activate

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
