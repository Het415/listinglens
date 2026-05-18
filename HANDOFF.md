# ListingLens — Session Handoff (2026-05-17, late session)

> Comprehensive resume context for a fresh chat (Claude Code, Cursor, or any tool). Everything you need to pick up is in this file.

---

## TL;DR

ListingLens is a deployed Amazon-review analyzer that was upgraded from a passive RAG demo (`/chat`) into an agentic Copilot (`/agent`). In this session those two AI surfaces were **collapsed into a single unified `/assistant` page with a manual Quick Q&A ↔ Copilot toggle** (Claude.app-style segmented control), backed by a single `POST /assistant/query` SSE endpoint that routes on a `mode` field. Chat history now persists across navigation. The Settings page was removed. Mobile UX for the trace panel was redesigned as a dropdown. A production deploy bug was found and fixed (the agent layer was never actually installed on Render, only nobody noticed). A new custom production domain `listinglens.hetprajapati.me` was wired up; the CORS fix to allow it is **merged but Render has not yet rebuilt** at time of writing — that is the only outstanding blocker.

---

## Live URLs

- **Frontend (custom domain, new):** https://listinglens.hetprajapati.me
- **Frontend (Vercel default):** https://listinglens-kappa.vercel.app
- **Backend API (Render):** https://listinglens-api.onrender.com
- **GitHub repo:** https://github.com/Het415/listinglens
- **LangSmith project:** `listinglens-copilot` at https://smith.langchain.com/projects

---

## Repo / worktree paths

- **Main repo:** `/Users/hetprajapati/github/listinglens/` (main branch checked out)
- **Worktree we worked in this session:** `/Users/hetprajapati/github/listinglens/.claude/worktrees/nifty-dirac-84511f/`
- **`.env` symlink:** the worktree's `.env` is a symlink to `/Users/hetprajapati/github/listinglens/.env` so both share the user's API keys
- **`frontend/.env.local`:** points at `https://listinglens-api-production.up.railway.app` (LEGACY/WRONG — the actual prod backend is on Render at `https://listinglens-api.onrender.com`). This file is gitignored-but-tracked and should NOT be committed with local changes. The live Vercel build must have `NEXT_PUBLIC_API_URL=https://listinglens-api.onrender.com` set in its environment for the dropdown / dashboard / assistant to work.
- **Python venv:** `.venv/` at the worktree root (Python 3.13 via uv on macOS; production Render uses Python 3.11)
- **Plan file (this session):** `/Users/hetprajapati/.claude/plans/users-hetprajapati-github-listinglens-c-snoopy-panda.md`
- **Memory files:** `/Users/hetprajapati/.claude/projects/-Users-hetprajapati-github-listinglens/memory/`

---

## Final architecture (after this session)

```
                    ┌──────────────────────────────────────────┐
                    │  Next.js 16 frontend (Vercel)            │
                    │  ├─ /                  landing + ASIN picker
                    │  ├─ /dashboard         scores / topics / charts
                    │  ├─ /dashboard/reviews per-review table
                    │  ├─ /dashboard/compare competitor diff
                    │  ├─ /assistant         ★ UNIFIED AI front door
                    │  ├─ /chat              v1 RAG (legacy, hidden from nav, URL still works)
                    │  └─ /agent             v2 Copilot (legacy, hidden from nav, URL still works)
                    └─────────────────┬────────────────────────┘
                                      │ SSE
                    ┌─────────────────▼────────────────────────┐
                    │  FastAPI backend (Render)                │
                    │  ├─ GET  /supported-asins                │
                    │  ├─ POST /analyze                        │
                    │  ├─ POST /chat                           │
                    │  ├─ POST /agent/query   (real agent)     │
                    │  ├─ POST /agent/query/mock (fixture)     │
                    │  └─ POST /assistant/query ★ NEW          │
                    │       routes on body.mode:               │
                    │         "quick"   → review_qa direct     │
                    │         "copilot" → run_agent_streaming  │
                    └─────────────────┬────────────────────────┘
                                      │
                    ┌─────────────────▼────────────────────────┐
                    │  LangGraph v1 multi-node agent           │
                    │  Planner → Executor → Synthesizer        │
                    │  (+ bounded re-plan loop)                │
                    └─────────────────┬────────────────────────┘
                                      │ MCP tools (5)
                    ┌─────────────────▼────────────────────────┐
                    │  ├─ review_qa          → src/rag_chatbot │
                    │  ├─ predict_return_risk → src/fusion XGB │
                    │  ├─ competitor_search  → mock seed       │
                    │  ├─ price_history      → mock seed       │
                    │  └─ trend_signal       → mock seed       │
                    └──────────────────────────────────────────┘
```

---

## Pre-session state (Stages 0–6 from the original Copilot plan)

All shipped before this session and are still in main:

| Stage | What shipped |
|---|---|
| 0 | `eval/gold_set.jsonl` — 30 hand-crafted queries (10 launch / 10 returns / 10 improve), with `expected_decision`, `expected_tools`, `expected_evidence_themes` |
| 1 | 5 MCP tools in `backend/mcp_server/tools/`: `review_qa`, `predict_return_risk` (wrap existing models), + `competitor_search` / `price_history` / `trend_signal` (mocks). Dual interface: Python functions AND `backend/mcp_server/server.py` FastMCP stdio server |
| 2 | `backend/agent/` single-node ReAct agent |
| 3 | Multi-node `Planner → Executor → Synthesizer` graph in `backend/agent/nodes/` with bounded re-plan loop |
| 4 | Eval harness in `eval/` — `run_eval.py`, `judges.py` (Claude Haiku 3 LLM-as-judge), `trajectory_eval.py` (F1 + ordering), `baselines.py`. Plus `.github/workflows/eval-on-pr.yml`. Stage 4 results: Trajectory F1 0.85, decision accuracy 56.7%, latency p50/p95 = 18.2s / 34.5s |
| 5 | `frontend/app/agent/` Next.js page with SSE streaming + Trace panel + Recommendation card. `POST /agent/query` (live) and `POST /agent/query/mock` (canned demo) endpoints. Deployed to Render + Vercel |
| 6 | README rewrite, `ARCHITECTURE.md` deep dive, sidebar nav updated, agent layout fixes, multiple rounds of UI polish |

Full pre-session detail was previously in this file (commit history if needed); this rewrite summarizes Stages 0-6 above and focuses on what happened in this session.

---

## What this session changed (in commit order on `main`)

All commits are on `main`. Five PRs were opened, all merged.

### PR #1 — three commits, the unified `/assistant` page

Merge commit: PR #1.

1. **`refactor(frontend): extract assistant components to shared dir`**
   - Pulled `AssistantMessage`, `RecommendationCard`, `TracePanel`, `ConfidenceRing`, the SSE reader, style helpers, and types out of `/chat/page.tsx` and `/agent/page.tsx` into [frontend/components/assistant/](frontend/components/assistant/).
   - `/chat` and `/agent` now import them. Pure refactor, no behavior change. Future polish only happens in one place.
2. **`feat(assistant): /assistant/query endpoint with quick vs copilot mode`**
   - New endpoint `POST /assistant/query` in [app.py](app.py).
   - New Pydantic model `AssistantQueryRequest(asin, query, mode)` where `mode ∈ {"quick","copilot"}`, defaulting to `"copilot"` if anything else.
   - Quick path: `await asyncio.to_thread(review_qa, asin, query)` — wraps the existing `backend/mcp_server/tools/review_qa.py`. Emits `started → node_started → tool_call → tool_result → node_completed → answer → done`. The `answer` event is new (quick-path equivalent of `recommendation`).
   - Copilot path: defers to `run_agent_streaming` from `backend/agent/graph.py`. Same event vocabulary the existing `/agent` page already understands.
   - First event is always `kind: {value: "quick"|"copilot"}` so the frontend can dispatch the right renderer.
   - Defensive imports inside the handler so a future break in `backend.agent.*` doesn't take down `/analyze` and `/chat`.
   - **The originally planned rule-based classifier was scrapped mid-session** — we built it, then the user requested a Claude.app-style segmented manual toggle instead, which is more honest UX (no hidden mis-classification). The classifier module `backend/assistant/router.py` was deleted in the same session.
3. **`feat(assistant): unified /assistant page + sidebar swap`**
   - New page [frontend/app/assistant/page.tsx](frontend/app/assistant/page.tsx) — sample queries, segmented `Quick Q&A | Copilot` toggle next to the input, mode-aware empty-state copy, mode-aware footer + placeholder.
   - New [frontend/app/assistant/layout.tsx](frontend/app/assistant/layout.tsx) — clones `/agent/layout.tsx` (h-screen + sidebar + topbar shell, same scroll-pin pattern).
   - Trace panel is always visible on desktop (per user choice, even in Quick mode it shows the minimal `review_qa` trace so the layout stays consistent across both modes).
   - Sidebar entries `Ask AI` (`/chat`) + `Copilot` (`/agent`) collapsed into a single `AI Assistant` (`/assistant`). The `/chat` and `/agent` routes still exist as direct-link URLs, just not surfaced in the nav.
   - ASIN-forwarding helper in [frontend/components/sidebar.tsx](frontend/components/sidebar.tsx) refactored to a `useAsinHrefs` hook for clarity.

### PR #2 — `fix(deploy): install agent deps as part of the main requirements.txt`

Merge commit: PR #2. **This is a critical latent prod fix.**

Discovered during deploy verification on the Vercel preview: every Copilot-mode submission returned `ModuleNotFoundError: No module named 'instructor'`. Investigation revealed:

- The production backend on Render had NEVER had `instructor`, `langgraph`, or `mcp` installed.
- The original `render.yaml` ran a second `pip install -r requirements-agent.txt` step that was failing silently. The first install (`requirements.txt`) succeeded, so the service came up healthy, just without the agent module.
- The `/agent/query` endpoint in production had the same `ModuleNotFoundError` for weeks but **nobody noticed** because the production Vercel build had `NEXT_PUBLIC_AGENT_LIVE` unset, which made the `/agent` page default to `/agent/query/mock`. No UI traffic ever exercised the real agent path.
- The new `/assistant` Copilot mode calls the real agent — that's what surfaced the latent bug.

**Fix:** folded `langgraph`, `mcp`, `instructor` into [requirements.txt](requirements.txt). Collapsed [render.yaml](render.yaml) to a single install step. Deliberately left `deepeval` and `langsmith` out — those are eval/tracing tools, not needed in the production runtime, and they're large.

### PR #3 — `feat(assistant): persist chat history per-ASIN across navigation`

User feedback: clicking any sidebar entry from `/assistant` blew away the chat. The page lived in `useState`, so unmount-on-route-change discarded everything.

Fix in [frontend/app/assistant/page.tsx](frontend/app/assistant/page.tsx):
- Mirror `messages` to `sessionStorage` keyed by ASIN: `assistant_history_<asin>`.
- Hydrate on mount via a `hydrated` flag (so the persist effect doesn't immediately overwrite stored history with the empty default during first render).
- Trace and loading state are intentionally NOT persisted — they're tied to in-flight requests.
- Added a small `Clear` button (only shown when `messages.length > 0`) next to the mode toggle so users can explicitly reset.

Per-ASIN scope: different products have separate conversations. Per-tab scope (sessionStorage, not localStorage): the chat doesn't pile up forever across days, and matches the existing pattern of `sessionStorage.getItem('analysis_${asin}')` already used by the page for product-name caching.

### PR #4 — `fix(ui): remove Settings nav + collapsible mobile trace dropdown`

Two unrelated UI fixes bundled because the user reported both at once:

1. **Settings page removed entirely.** It was a placeholder ("Account settings coming soon...") at [frontend/app/dashboard/settings/page.tsx](frontend/app/dashboard/settings/page.tsx). Clicking the sidebar entry stripped the `?asin=` query param, causing the entire dashboard to fall back to the default TOZO T10 product context on every subsequent page. Deleted the route + sidebar/MobileNav entries.
2. **Mobile trace as a collapsible dropdown.** On desktop, agent trace lives in a 360px right rail. On mobile, the same panel was stacking below the chat as a 300px-tall block, crowding small viewports. Now mobile renders the trace as a single-line dropdown above the chat — `Agent trace · idle / N events · ▾` — that expands to a 260px tray on tap. Auto-expands while the agent is streaming so users see progress without tapping. Desktop layout is unchanged.
   - **Implementation note:** used controlled React `useState` rather than native `<details>`. Native `<details>` was leaving its body partially visible (~140px) even when closed — almost certainly some Tailwind-preflight or global stylesheet override of the user-agent `details:not([open]) > *:not(summary) { display: none }` rule. Did not chase it down; controlled state is more predictable anyway.
   - Added `grid-rows-[auto_1fr]` on mobile so the trace row sizes to its content. Without this, `grid-cols-1` alone let the implicit auto rows stretch to ~186px even with only 44px of content (grid was implicitly making both rows equal-ish under default `align-items: stretch`).
   - `TracePanel` grew a `hideHeader?: boolean` prop so the mobile dropdown's `<button>` can serve as the title without duplicating "Agent trace" inside.

### PR #5 — `fix(cors): allow listinglens.hetprajapati.me custom domain`

User deployed the frontend to a custom domain. Every API call CORS-blocked because the backend's `_default_cors` in [app.py](app.py) only listed `listinglens-five.vercel.app` (stale) plus a `https://.*\.vercel\.app` regex. The custom domain matched neither.

Fix: added `https://listinglens.hetprajapati.me` and the current `https://listinglens-kappa.vercel.app` to the default allowlist. Left the `CORS_ALLOWED_ORIGINS` env-var override path intact for future domains.

**⚠️ CURRENT BLOCKER:** as of the end of this session, the merged PR's code is on `main` (commit `925284e2`, merge `6921050c`) **but Render has NOT yet rebuilt with it.** The user attempted a manual deploy. Diagnostic test:

```bash
curl -sI -X OPTIONS https://listinglens-api.onrender.com/supported-asins \
  -H "Origin: https://listinglens.hetprajapati.me" \
  -H "Access-Control-Request-Method: GET"
# Still returns HTTP/2 400 with NO access-control-allow-origin → still old code
```

The new code would have OPTIONS return 200 with `access-control-allow-origin: https://listinglens.hetprajapati.me`. Until that flips, **the landing page dropdown, dashboard, and `/assistant` all break on the custom domain** with the same root cause: backend returns 200 but the response lacks the CORS header for the new origin, so the browser blocks the JS from reading the body.

**To unblock when picking this up:**
1. Check https://dashboard.render.com → `listinglens-api` service → **Events** tab
2. If the deploy is still in progress (FAISS/torch/transformers stack takes 8–15 min on free tier), just wait
3. If the deploy failed, click into the failed build and read the log — pip-install is the usual culprit for this stack
4. If auto-deploy is off, toggle it on in Settings, then click Manual Deploy → Deploy latest commit
5. Re-run the curl above; once it shows the ACAO header, the entire app starts working on the custom domain end to end with **no further code changes needed**

---

## Files touched this session (summary, by area)

### Backend
- [app.py](app.py)
  - New `AssistantQueryRequest` Pydantic model with `mode` field
  - New `POST /assistant/query` endpoint
  - CORS `_default_cors` updated with new custom domain + kappa Vercel
- [requirements.txt](requirements.txt) — added `langgraph`, `mcp`, `instructor` (the prod-install fix)
- [render.yaml](render.yaml) — collapsed to single install step
- `backend/assistant/` — directory created mid-session for rule-based classifier, **then deleted** when user pivoted to manual toggle. No remnants.

### Frontend
- [frontend/components/assistant/](frontend/components/assistant/) — NEW shared component directory
  - `AssistantMessage.tsx`
  - `RecommendationCard.tsx`
  - `TracePanel.tsx` (with `hideHeader` prop added later)
  - `ConfidenceRing.tsx`
  - `sse.ts` (the `readSSE` async generator)
  - `style-helpers.ts` (`ratingStyle`, `sentimentBadge`, `decisionStyle`, `recommendationToText`, `chatAnswerToText`, `toolMeta`, `TOOL_META`)
  - `types.ts` (`Message`, `SourceItem`, `Recommendation`, `TraceStep`, `EvidenceItem`, `ChatMessage`)
- [frontend/app/assistant/layout.tsx](frontend/app/assistant/layout.tsx) — NEW, clones `/agent/layout.tsx`
- [frontend/app/assistant/page.tsx](frontend/app/assistant/page.tsx) — NEW, the unified page with mode toggle + sessionStorage persistence + mobile trace dropdown
- [frontend/app/chat/page.tsx](frontend/app/chat/page.tsx) — refactored to import shared components
- [frontend/app/agent/page.tsx](frontend/app/agent/page.tsx) — refactored to import shared components
- [frontend/components/sidebar.tsx](frontend/components/sidebar.tsx) — `Ask AI` + `Copilot` collapsed into single `AI Assistant`; Settings entry removed
- `frontend/app/dashboard/settings/` — DELETED

### Memory files written
- `/Users/hetprajapati/.claude/projects/-Users-hetprajapati-github-listinglens/memory/MEMORY.md`
- `user_communication.md` — user wants detailed educational explanations, picks recommended options
- `project_copilot_upgrade.md` — full project context

---

## Critical gotchas (carry-over from previous handoff, still apply)

1. **`ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` shadowing.** Claude Code's parent shell exports its own keys that override `.env`. Any script that hits Anthropic needs `load_dotenv(override=True)` AND `os.environ.pop('ANTHROPIC_BASE_URL', None)`. Already wired into `eval/run_eval.py`.
2. **Groq daily TPD cap is 500k tokens** on free tier. The Stage 4 eval used ~498k. Quota resets at UTC midnight.
3. **`min-h-screen` on layouts causes page-level scroll** when content is taller than viewport. Use `h-screen overflow-hidden` instead — `/agent/layout.tsx`, `/chat/layout.tsx`, and `/assistant/layout.tsx` are all on this pattern.
4. **Llama 3.3 70B on Groq emits malformed tool_calls** on tool-heavy prompts. The agent uses `meta-llama/llama-4-scout-17b-16e-instruct` instead. v1 `/chat` still uses Llama 3.3 because it doesn't do tool-calling. The `AGENT_MODEL` env var on Render pins this.
5. **`/agent/query/mock` always streams the same canned TOZO returns scenario** regardless of input — by design, a development fixture. The live endpoint is `/agent/query`. Vercel env `NEXT_PUBLIC_AGENT_LIVE=true` flips the existing `/agent` page from mock to live; the new `/assistant` page **always** calls the live `/assistant/query` and has no mock fallback.
6. **Frontend uses `fetch` + `ReadableStream` for SSE**, not `EventSource`. The shared reader is at [frontend/components/assistant/sse.ts](frontend/components/assistant/sse.ts).
7. **`frontend/.env.local` is tracked in git despite being in `.gitignore`** because it was committed before the gitignore was added. Local changes should NOT be committed (`git restore --staged` before committing other things). Its current value (Railway URL) is **wrong**; the right value for production is in the Vercel env vars, not this file.
8. **Always verify UI changes in browser preview before committing.** Verification flow used this session: `preview_start`, `preview_eval` to navigate, `preview_eval` with DOM queries to assert structure, `preview_screenshot` for visual proof, `preview_stop`. Mobile bugs are easy to miss; resize to 375px and re-check.
9. **macOS dev:** `torch==2.1.0+cpu` from requirements.txt is Linux-only. Install plain `torch` from PyPI. `brew install libomp` for XGBoost.
10. **Sync function calls inside async SSE generators block the event loop.** In `/assistant/query` we use `await asyncio.to_thread(review_qa, ...)` for the quick path so the stream stays flushable. Earlier attempts with `loop.run_in_executor` deadlocked on FAISS init — `asyncio.to_thread` works cleanly.

---

## Eval results (still from Stage 4, no re-run this session)

30 queries, full agent, Claude Haiku 3 judge:

| Metric | Value |
|---|---|
| **Trajectory F1** | **0.850** (precision 0.92, recall 0.82) |
| First-tool match rate | 66.7% |
| **Decision accuracy** | **56.7%** (17/30 vs gold) |
| Judge: decision_correctness | 0.431 |
| Judge: evidence_relevance | 0.444 |
| Judge: anti_hallucination | 0.737 |
| Judge: completeness | 0.759 |
| Latency p50 / p95 | 18.2s / 34.5s |
| Error rate | 10% (3 Groq daily-TPD-cap hits) |

**Honest read:** trajectory is the strongest signal — the planner picks the right tools. Decision accuracy is moderate because the agent over-confidently predicts `go` on launch queries where the gold expects `needs_more_data` or `no_go`. This is the most career-signal-worthy open item from the original 6-stage plan.

Report: [eval/reports/2026-05-16-full.md](eval/reports/2026-05-16-full.md)

---

## What's queued / open threads

### IMMEDIATE blocker (must do first)

1. **Verify Render finished deploying the CORS fix.** Curl test above. Until this flips, the custom domain frontend can't talk to the backend at all. Most likely the deploy is mid-build or auto-deploy is disabled. See the "PR #5 → CURRENT BLOCKER" section above for the exact diagnostic steps.
2. **Verify `NEXT_PUBLIC_API_URL` in the Vercel project for `listinglens.hetprajapati.me`.** Should be `https://listinglens-api.onrender.com`. If it's still pointing at the old Railway URL (`listinglens-api-production.up.railway.app`), CORS won't matter — the frontend is hitting a dead host. Vercel → Project → Settings → Environment Variables.

### Suggested next features (audited this session, ranked by impact)

A dashboard audit was run at end-of-session. Findings, in order of impact:

1. **🔥 Wire dashboard cards to `/assistant`.** This is the highest-impact single change. Every dashboard card surfaces a *problem* but no action. Quality Breakdown says "Image count: only 3, need 7+" with no fix button. Topic Analysis shows "battery complaints" with no "How do I address this?" link. Plan: add an **Ask AI about this** button on each card that opens `/assistant?asin=…&q=<pre-filled question>&mode=copilot`. Dashboard becomes a launchpad instead of a dead end, and justifies the unified assistant we just built. Files involved: [frontend/components/dashboard/topic-analysis.tsx](frontend/components/dashboard/topic-analysis.tsx), [frontend/components/dashboard/quality-breakdown.tsx](frontend/components/dashboard/quality-breakdown.tsx), [frontend/app/assistant/page.tsx](frontend/app/assistant/page.tsx) (needs to accept `?q=` URL param and auto-submit).
2. **Onboarding for first-time sellers.** Landing on `/dashboard` with no `?asin=` query param silently loads the TOZO T10 demo. No banner, no guidance. Either land on a "paste an ASIN or pick a demo product" screen, or show a "← This is the TOZO demo. Try your own ASIN" banner with a link to the landing page picker. Hardcoded fallback at [frontend/app/dashboard/page.tsx:21](frontend/app/dashboard/page.tsx:21) and [frontend/app/dashboard/reviews/page.tsx:136](frontend/app/dashboard/reviews/page.tsx:136).
3. **Remove the dead `/dashboard/visual` route.** It's a placeholder stub at [frontend/app/dashboard/visual/page.tsx](frontend/app/dashboard/visual/page.tsx), not linked from anywhere in the sidebar, uses stale theme tokens (`text-text-primary` instead of `text-foreground`). Either ship the CLIP visual-analysis feature it promises, or delete it like we did Settings.
4. **Surface real error messages on backend failure.** Dashboard catches everything and shows a generic red box at [frontend/app/dashboard/page.tsx:75–79](frontend/app/dashboard/page.tsx:75). User has no idea if it's a missing ASIN, 500, or network. Let the error message through.
5. **Unify loading states across `/dashboard`, `/dashboard/reviews`, `/dashboard/compare`.** Main page spins, reviews shows skeleton cards, compare has a third style. Pick one (probably skeletons) and apply everywhere.
6. **Audit mobile UX of `/dashboard` and `/dashboard/reviews` and `/dashboard/compare`.** We fixed `/assistant` mobile this session, but the dashboard pages were never checked. The 4-col score cards collapse fine, but the topbar Export button and product breadcrumb may clip on narrow viewports. Screenshot at 375px.
7. **Fix decision accuracy on launch queries (the eval's biggest weakness).** Most career-signal-worthy item still open from original plan. The agent over-confidently predicts `go` on launch queries where gold says `needs_more_data` or `no_go`. Plan: iterate the Planner prompt in [backend/agent/prompts.py](backend/agent/prompts.py) to be more conservative about uncertainty. Run eval after each iteration: `python -m eval.run_eval --limit 5 --no-judge` for cost-free smoke, full 30-query with judge when ready.
8. **Competitor Compare auto-populate.** Currently you must manually pick 2-3 ASINs. If the dashboard knows the current product, pre-fill compare with the top-3 competitors from the existing `competitor_search` tool — one click to "Compare against top 3 competitors."
9. **Record the Loom demo.** Stage 6 originally called for it. Was never done. With the unified `/assistant` page this is the natural recording target.

The user has rate-limited Claude Code for the month and is moving to Cursor — items 1 and 2 are the natural pick-ups since they're concrete, the audit already exists, and they ship visible product polish without needing to wait for the Render redeploy to finish.

---

## How to start the next session (Cursor or otherwise)

Tell the new agent:

> Read `HANDOFF.md` in the repo root. Resume from the "What's queued / open threads" section. The immediate blocker is the Render redeploy from PR #5 — verify it's finished by curling `https://listinglens-api.onrender.com/supported-asins` with `Origin: https://listinglens.hetprajapati.me` and checking for the `access-control-allow-origin` response header. Once that's confirmed live, pick up item #1 (wire dashboard cards to `/assistant`).

The plan file at `/Users/hetprajapati/.claude/plans/users-hetprajapati-github-listinglens-c-snoopy-panda.md` has the original `/assistant` design plan that was approved at the start of this session; you can read it for additional context but everything material from it has been implemented.

---

## Useful local commands

```bash
# Activate venv
cd /Users/hetprajapati/github/listinglens
source .venv/bin/activate

# Run agent from CLI
python -m backend.agent.run --asin B08XPWDSWW "Why are returns spiking?" --pretty

# Run eval (no judge — cost-free)
python -m eval.run_eval --limit 5 --no-judge --output-tag smoke

# Run eval with judge (needs ANTHROPIC_API_KEY)
python -m eval.run_eval --limit 5

# Local backend
uvicorn app:app --host 127.0.0.1 --port 8000 --log-level warning

# Local frontend
cd frontend && npm run dev   # http://localhost:3000

# Test the new /assistant/query endpoint locally
curl -N -X POST http://127.0.0.1:8000/assistant/query \
  -H "Content-Type: application/json" \
  -d '{"asin":"B08XPWDSWW","query":"what do 1-star reviews say?","mode":"quick"}'

# Check production CORS
curl -sI -H "Origin: https://listinglens.hetprajapati.me" \
  https://listinglens-api.onrender.com/supported-asins | grep -i access-control

# Check production health
curl https://listinglens-api.onrender.com/health
```

---

## Commits on `main` from this session (most recent first)

```
6921050c Merge pull request #5 from Het415/fix/cors-custom-domain
925284e2 fix(cors): allow the custom production domain (listinglens.hetprajapati.me)
fe2ecfbd Merge pull request #4 from Het415/fix/remove-settings-mobile-trace
f5170d96 fix(ui): remove Settings nav, collapse mobile trace into dropdown
decf16d7 Merge pull request #3 from Het415/feat/assistant-history
c26cf00d feat(assistant): persist chat history per-ASIN across navigation
576cc87b Merge pull request #2 from Het415/fix/install-agent-deps
d2f85bae fix(deploy): install agent deps as part of the main requirements.txt
28fd1f7b Merge pull request #1 from Het415/claude/nifty-dirac-84511f
f1cef6e5 feat(assistant): unified /assistant page + sidebar swap
5136181c feat(assistant): /assistant/query endpoint with quick vs copilot mode
0fba187c refactor(frontend): extract assistant components to shared dir
```

---

*End of handoff. Pick up by verifying the Render deploy is live, then move to dashboard wiring.*
