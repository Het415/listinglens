# ListingLens — Session Handoff (2026-09-17, Claude Code / Opus 5)

> Pickup context for the next chat. Self-contained — you don't need to read any other handoff doc to continue.

---

## TL;DR

ListingLens is a deployed agentic Amazon-review analysis platform with three frontend
surfaces (`/dashboard`, `/dashboard/reviews`, `/assistant`) and a FastAPI backend on
Render. **This session was infrastructure, not features.** Production had been down —
Groq decommissioned the entire Llama family — and the local environment had silently
drifted away from what production installed.

What changed, all deployed and live at `1d388b75`:

- **Production Copilot fixed.** Groq model config centralised in `src/llm_config.py`
  with per-stage fallback chains; `scripts/doctor.py` preflights against Groq's live
  catalog. Every Copilot query was 404-ing; now serves grounded answers in ~22s.
- **Runtime aligned on Python 3.13** across `.python-version`, Dockerfile, both
  workflows. `pip install -r requirements.txt` works on macOS for the first time (the
  old `torch==2.1.0+cpu` pin was unsatisfiable there).
- **Embeddings moved off torch to onnxruntime.** RAG memory 651MiB → 380MiB, image
  3.59GB → 2.48GB, all 12 FAISS indexes reproducing at cosine 1.000000 (no re-indexing).
  Under a hard 512MB cap the old build was OOM-killed on the first query.
- **Two long-standing mysteries closed.** The test suite's phantom failures were
  `deepeval` loading `.env` before `conftest.py` via its pytest plugin entry point
  (gotcha #13). The SIGSEGV logged for months as unreproducible is FAISS-then-XGBoost in
  one process (gotcha #11) — `OMP_NUM_THREADS=1` fixes it, `KMP_DUPLICATE_LIB_OK` does not.
- **Eval baseline re-established**: first judged 30-query run since May. Error rate
  33.3% → 3.3%, decision accuracy 40% → 60%, all four judge dimensions up.

### Update — later on 2026-09-17 (second session)

Worked the DEMO-READINESS PLAN below. **P0 and P1 are done except for one manual step
that needs you**, and two things were found along the way that were not on the list.

- **P0, warmup — half done.** `/warmup` verified end-to-end; a launchd agent now pings
  it every 5 min while this Mac is awake; `scripts/predemo_check.sh` is a one-command
  demo preflight. ⚠️ **You still need to create the cron-job.org job** (~2 min,
  field-by-field config in `docs/WARMUP.md`) — an account on a third-party service had
  to be created, which could not be done for you. Until then the service still sleeps
  whenever your Mac is off.
- **P1, `/dashboard/visual` — done**, and the bigger version of the same problem with
  it: the **landing page advertised a CLIP-based "Visual Quality Score" that does not
  exist anywhere in the backend** (`grep -ri clip app.py backend src` → nothing), in
  four places including the page title. Deleting the placeholder route alone would have
  left all four claims standing. Replaced with what is actually built.
- **P1, `tool_use_failed` — fixed and VERIFIED end-to-end.** A full judged run caught
  the retry firing on `returns_004`, where the model wrote `"confidence": 0. nine` into
  an otherwise perfect payload; one same-model retry recovered it to a correct `go`.
  The Synthesizer degrade fired twice and was bucketed correctly. **But the run also
  established that this harness has a ~11-row noise floor** — 11 of 24 like-for-like
  rows flip between runs of identical code — so no single-run accuracy delta from it
  means anything. Both points in "Detail — `tool_use_failed`".
- **Found and fixed while measuring: the Executor had the same bug as the Synthesizer.**
  A rate-limit-exhausted chain hit a bare `raise`, killing 3 of 30 queries with
  `tools_called == []`. Fixed (`be38fec9`), unit-tested, not yet verified end-to-end.
- **Also fixed: the eval was about to score a degraded run as a real answer.** Caught
  before quoting any number from it — see queue #19.
- **The gold set itself was the weakest link, and is now repaired.** `expected_decision`
  was near-determined by `query_type`, so a three-entry lookup table scored 76.7% against
  the agent's 60.0%. Only `launch` is scored now, three `no_go` cases were added (it had
  2, so the capability was unmeasurable), and four rows demanding percentages retrieval
  cannot produce were repaired. 33 rows; the launch floor fell to 46.2%.
- **Latest run (2026-09-20) is the cleanest this project has had: 33/33, zero errors,
  zero degraded.** The three new `no_go` cases passed 3/3 first try. Read the
  "Run on the rebalanced gold set" section before quoting any number from it — the
  nine-point accuracy rise is the benchmark sharpening, not the agent improving.
- **Found: `pytest` segfaulted on macOS** without `OMP_NUM_THREADS=1` — the same OpenMP
  bug as gotcha #11, but the existing fix did not cover the test suite. Pinned in
  `tests/conftest.py`; suite is 27 tests in ~4s, 3/3 clean.
- **Found and REVERTED: a fallback-chain reorder.** Worth reading before you touch
  `FALLBACK_CHAINS` — the evidence for it looked solid and was backwards. Details in
  "Measured per-model reliability".
- **Corrected: `.env` DOES have `ANTHROPIC_API_KEY`** (the note below said it did not),
  and Groq's binding rate limit is TPD, not TPM (gotcha #2).

⚠️ **Your Render builds are not failing.** 2 failures in 59 deploys, both 2026-04-21.
`deactivated` in Render's history means *superseded by a newer deploy*, not failed — a
healthy history is one `live` and many `deactivated`. This confused a whole debugging
session; don't re-derive it.

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
  - ✅ **`ANTHROPIC_API_KEY` IS in `.env`** — corrected 2026-09-17 (later the same day; the paragraph this replaces said it was absent). The judge can run. Two things to know:
    - The line had a **stray space after the `=`** (`ANTHROPIC_API_KEY= sk-ant-…`). `python-dotenv` strips it so every Python path worked, but `source .env` in zsh parsed it as an empty assignment followed by a command, printing the whole secret into the terminal as `command not found`. Fixed. **Don't `source .env`** — `scripts/predemo_check.sh` has an `env_get` helper that `sed`s out one value instead.
    - `eval/run_eval.py` preflights the key and exits 1 with instructions, so a judged run fails fast rather than silently scoring zeros.
- **Frontend:** `frontend/` — Next.js 16, React 19, Tailwind v4. `node_modules` may be sparse in some environments; run `npm install` if needed.
- **Frontend env (production):** Vercel must have `NEXT_PUBLIC_API_URL=https://listinglens-api.onrender.com`. ~~`frontend/.env.example` and `frontend/.env.local` point at a deprecated Railway URL — do NOT trust them.~~ **Corrected 2026-09-17:** both now read `https://listinglens-api.onrender.com`. The warning was itself stale.

---

## Inherited context (one paragraph)

A prior Claude Code session (`HANDOFF.md` on the unmerged `origin/docs/session-handoff` branch) shipped: a unified `/assistant` page with manual Quick-Q&A vs Copilot mode toggle backed by `POST /assistant/query`; per-ASIN sessionStorage chat history; mobile trace dropdown; removal of the Settings page; deploy-fix that folded `langgraph`/`mcp`/`instructor` into the main `requirements.txt` (the agent layer had been silently uninstalled in production for weeks but nobody noticed because the live `/agent` page used a mock fallback); CORS allowlist update for the new custom domain. That session ended with the CORS fix merged but not yet redeployed by Render — **that has since deployed and the custom domain works end-to-end.** All work from that session is on `main`.

If you ever need the full 346-line prior handoff, it's at:
```
git show origin/docs/session-handoff:HANDOFF.md
```

---

## Historical — what the 2026-05-18 session shipped

> Kept for provenance. For the 2026-09-17 session see the TL;DR, the three dated
> sections lower down, and the commit log at the bottom.

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

## Historical — eval state as of 2026-05-18

> ⚠️ Superseded. The current numbers are in "Eval baseline re-established
> (2026-09-17)" below, which supersedes every figure in this section — the agent
> models changed completely (Llama family → gpt-oss/qwen) in between.

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
| 3 | Delete or build out `/dashboard/visual` placeholder | ✅ done — same item as #13 below (it was double-listed) |
| 4 | Surface real backend error messages on dashboard fetch failures | ⚠️ partly done — `/assistant` done (`267d0288`: `user_facing_error` + `ErrorBubble`); the `/dashboard/*` fetch failures named in this row are still raw |
| 5 | Unify loading states across `/dashboard/*` (spinner vs skeleton vs third style) | ✅ done (`d5023158`) — it was five styles, not three. One `components/dashboard/loading.tsx`; 0 spinners and 0 hand-rolled pulse blocks left |
| 6 | Mobile QA pass on `/dashboard/*` (we did `/assistant` last session) | open — **audited, not fixed**. Full findings below under "Mobile audit". The premise that mobile nav is missing is WRONG (`MobileNav` exists); the real P0s are the tab bar overflowing <390px and two tabs highlighting at once |
| 7 | Planner prompt tuning to fix launch-query over-confidence | open — **and the premise is inverted**. Measured: launch is the BEST type (7/10), zero wrong `go`s; the agent UNDER-commits. See "Planner diagnosis" below before touching prompts |
| 16 | Synthesizer loses a completed run to one malformed generation | ✅ done (`16e13489`) — degrades to evidence assembled from tool results; 7 tests. **Degrade observed firing twice on the post-fix judged run** |
| 20 | Executor loses a completed run when its model chain is rate-limited | ✅ done (`be38fec9`) — 12 tests, but **STILL not verified end-to-end**. The 2026-09-20 run could not exercise it: nothing failed. Needs a forced failure or a genuinely exhausted budget |
| 21 | This eval cannot detect a change smaller than ~11 rows in one run | ⚠️ **open measurement constraint, not a bug** — 11 of 24 like-for-like rows flipped between two runs of identical code. Read before trusting any single-run delta |
| 22 | Gold set was degenerate: decision label near-determined by `query_type` | ✅ done (`6280fb44`) — only `launch` scored, 3 `no_go` rows added, 4 unwinnable rows repaired. 33 rows; launch floor 60.0% → 46.2% |
| 23 | Raise the 1500-char tool-result cap in `synthesizer.py:39-40` | **open — highest-value item left.** Diagnosed mechanism, ~175 tokens/run, and `evidence_relevance` is sitting flat at 0.548 waiting to confirm it |
| 17 | Raw provider stacktraces rendered in the chat UI | ✅ done (`267d0288`) — `user_facing_error` + `ErrorBubble`; 8 tests assert the Groq org id cannot reach the browser |
| 18 | Production diagnostics arrive late or not at all | ✅ done (`327bd2e4`) — `render.yaml` uses `env: python`, so the Dockerfile's `PYTHONUNBUFFERED=1` never applied |
| 19 | Eval scored a degraded run as a real `needs_more_data` answer | ✅ done (`a3b587c0`, tests `333906c1`) — `no_decision_rate` is the figure comparable to historical `error_rate` |
| **12** | **Cold start: warmup cron doesn't actually run (~4h, not 10min)** | ⚠️ half done — local launchd pinger installed; **YOU still need to create the cron-job.org job**, see `docs/WARMUP.md` |
| 10 | Make `tool_use_failed` retryable (instructor predicate) | ✅ done — `resilient_call` now retries same-model once then fails over; 8 unit tests in `tests/test_llm_config.py` |
| 13 | Delete/hide `/dashboard/visual` "coming soon" placeholder | ✅ done — route deleted; also removed the landing page's unimplemented CLIP/"multimodal" claims |
| 14 | `pytest` segfaults on macOS without `OMP_NUM_THREADS=1` | ✅ done — pinned in `tests/conftest.py` |
| 15 | ~~Agent fallback chain ends on `qwen/qwen3.8-27b`, whose OTPM limit is too small for a Synthesizer `Recommendation`~~ | ❌ **not a defect — investigated and closed.** This row recorded a wrong hypothesis before the A/B disproved it: qwen handles the real schema, the proposed replacement did not, and the 429s were the daily token cap. Do not act on it; see "Measured per-model reliability" |
| 11 | Retrieval ranking: `evidence_relevance` is the weakest judge dimension (0.545) | P3 |
| 8 | Auto-populate Competitor Compare from `competitor_search`  | open (alternative pickup) |
| 9 | Record the Loom demo (originally Stage 6) | open |

---

## ★ DEMO-READINESS PLAN — do these, in this order

Goal: the project is **showable live in an interview with no lag and nothing visibly
unfinished**. Ordered by demo impact, not by feature value. P0 alone is most of the win.

### P0 — this is what kills a live demo  ⚠️ HALF DONE — ONE MANUAL STEP LEFT

**1. The service is asleep when your interviewer clicks the link.**

`.github/workflows/warmup.yml` is configured `cron: '*/10 * * * *'`, but GitHub throttles
scheduled workflows on free accounts and **actually runs it every ~4 hours** — measured
gaps 2026-09-14→16: 212, 241, 322, 294, 137, 163, 187, 293, 326, 299, 141 min (median
241). Render free tier sleeps after ~15 min idle, so the instance is down almost always.
Measured cold starts on `/health`: **32.7s and 81.3s**.

The repo *looks* like it warms every 10 minutes. It does not. Do not trust the cron.
`warmup.yml`'s header comment now says so in large letters, so nobody re-derives it.

**What is done (2026-09-17):**

- `/warmup` verified end-to-end: returns in 0.2s, and `/health`'s `cached_asins` shows
  the demo ASIN within 10s. The endpoint was never the problem; nothing was calling it.
- **Local pinger installed.** `scripts/warmup_ping.sh` + a launchd agent at
  `~/Library/LaunchAgents/com.listinglens.warmup.plist`, `StartInterval 300`,
  `RunAtLoad`. Logs one bounded line per ping to
  `~/Library/Logs/listinglens-warmup.log`, tagged `warm` / `COLD-START` /
  `UNREACHABLE`. Verified loaded, exit 0. This covers the window that matters most —
  a live demo happens while your Mac is awake.
- **`scripts/predemo_check.sh`** — run it 2-3 min before any demo. Checks backend
  latency, hydrates the demo ASIN if cold, compares the *live* commit (via the Render
  API, not `/health`) against local HEAD, warns on a dirty tree, checks the frontend,
  and confirms the launchd agent is loaded. Exit 0 = demo-ready.

**What YOU still have to do — ~2 minutes, and it is the 24/7 half:**

Create the external cron job. An account had to be created on a third-party service, so
it could not be done for you. Field-by-field config is in **`docs/WARMUP.md`** — sign in
at cron-job.org, `POST https://listinglens-api.onrender.com/warmup`, body
`{"asin":"B08XPWDSWW"}`, every 5 minutes, 120s timeout. Prefer cron-job.org over
UptimeRobot: UptimeRobot's free tier only sends GETs, so the body is dropped and you get
process-alive-only warming rather than a preloaded FAISS index.

Without it, the service still sleeps whenever your Mac is off — so a link an interviewer
opens the next morning is cold.

If you want certainty for a scheduled interview, Render **Starter ($7/mo) removes
spin-down entirely** and makes all of the above unnecessary. Worth one month's spend
around interview season.

**Rehearsal rule:** run `scripts/predemo_check.sh` before any demo regardless.

### P1 — visible discrepancies an interviewer will land on  ✅ DONE

**2. `/dashboard/visual`** — deleted. The route is gone (`npm run build` confirms it is
no longer in the route table; the path now 404s). It had no sidebar entry to remove —
the prior handoff assumed one existed, and it did not.

**The bigger find, in the same category:** the **landing page advertised a feature that
does not exist anywhere in the backend.** `grep -ri clip app.py backend src` returns
nothing, yet `/` showed a feature card reading *"Visual Quality Score — CLIP model
analyzes your product images…"*, a trust badge reading *"Vision + NLP + LLM"*, a
headline promising *"multimodal AI analysis of your listing quality"*, and a page title
of *"Multimodal Product Intelligence Platform"*. Deleting the placeholder route alone
would have left all four claims standing — and an interviewer who reads the landing page
asks to see the visual score. Replaced with what is actually built:

- feature card → **"Agentic Copilot"** (plans across five real tools, cites evidence)
- trust badge → **"NLP + XGBoost + LLM agent"**
- headline subcopy → review sentiment / return risk / complaints, "an agent that cites
  its sources"
- `layout.tsx` title → **"Agentic Product Intelligence Platform"**

Also fixed a stale comment in `page.tsx` (`setLoadingStep(2) // "Scoring images..."`
when `loadingSteps[2]` is `'Building knowledge base...'`).

Swept the rest of the frontend for `coming soon` / `not implemented` / `TODO` — clean.

**3. `tool_use_failed`** — fixed in `src/llm_config.py`. Details in the next section.

### P2 — polish, do if time remains

**4. Unify loading states** across `/dashboard/*` (queue #5) — currently spinner vs
skeleton vs a third style. Agent runs take **p50 33s, p95 48s** (7/30 queries over 45s),
so the loading experience *is* the experience for half a minute. The SSE stream already
emits `node_started` / `tool_call` / `tool_result`; make sure every surface renders that
progress rather than an indefinite spinner. This converts "it's laggy" into "it's showing
me its reasoning", which is the whole pitch of the project.

**5. Mobile pass on `/dashboard/*`** (queue #6). `/assistant` was done; the dashboard was
not. Interviewers do open things on phones.

### P3 — substance, for the questions they'll actually ask

**6. `evidence_relevance` is your weakest judge dimension at 0.545** — consistent across
runs (0.60 on a 3-query smoke, 0.545 over 30). With completeness 0.876 and
anti-hallucination 0.811, the pattern is thorough, non-fabricated answers citing
weakly-relevant evidence. That is retrieval ranking, not generation: look at
`FILTERED_FETCH_K`, chunk size (300 chars is small), and the rating-filter path in
`src/rag_chatbot.py`. This is the most defensible "here's what I'd improve next" answer
you can give, because it is measured.

**7. Planner over-confidence on launch queries** (queue #7) — judge scores now exist, so
this is unblocked. Decision accuracy is 60%; trajectory recall (0.750) is lower than
precision (0.865), meaning the agent calls fewer tools than the gold set expects.

### Deliberately NOT before an interview

- **Competitor Compare auto-populate** (#8). New surface area plus an unresolved honesty
  problem — the mock competitor ASINs aren't in the analyzed catalog, so the UI would have
  to visibly distinguish synthetic cards. High risk of introducing a fresh discrepancy.
- **Loom demo** (#9). Record it *after* P0–P1, or you will re-record it.

### Interview talking points, since the work is already done

Lead with what is measured, not what is built:

- **Reliability engineering**: Groq decommissioned an entire model family and took
  production down. Response was per-stage fallback chains (`resilient_call`) plus a
  preflight (`scripts/doctor.py`) that validates every pin against the live catalog.
  Measured outcome: eval error rate 33.3% → 3.3%; 34 rate-limit failovers absorbed in one
  30-query run with zero lost queries.
- **Profiling over guessing**: the RAG path used 651MiB and was OOM-killed under a 512MB
  cap. Profiling showed ~490MiB was *framework import overhead* (torch 212MiB,
  sentence-transformers 276MiB) against an 87MiB model. Replacing it with onnxruntime cut
  it to 380MiB and the image from 3.59GB to 2.48GB — while proving vector compatibility
  at cosine 1.000000 against the committed indexes, so nothing had to be re-indexed.
- **Knowing what "verified" means**: the embedding swap was validated by reconstructing
  stored vectors from the FAISS index and re-embedding the source text, not by eyeballing
  search results — because plausible-looking results are exactly what silent embedding
  drift produces. `tests/test_onnx_embeddings.py` makes that a CI gate.
- **Honest evaluation**: the eval had been reporting a judge model on runs where judging
  never ran. Fixed the report, and the current numbers are a real judged baseline.

---

## Detail — `tool_use_failed` (P1 item 3)

**Status: fixed, unit-tested, and VERIFIED end-to-end on a full judged run.** The retry
fired on real traffic and recovered a query that would previously have died — evidence
under "Verified end-to-end" below, along with the run's confound and a noise-floor
finding that changes how any future eval result should be read.

### What the fix is

`src/llm_config.py`. `_failover_reason` now recognises a third class of error alongside
`_MODEL_GONE` and `_RATE_LIMITED`:

```python
_TOOL_CALL_MALFORMED = (
    "tool_use_failed",
    "failed to parse tool call arguments",
    "tool call validation failed",
)
```

and `resilient_call` **retries the same model once** before advancing the chain
(`_SAME_MODEL_RETRIES`), because this failure is stochastic. Decommissioning and rate
limits still advance immediately — retrying a 404 is pointless.

Worst case is bounded: `len(chain)` attempts plus one extra per model, so 6 calls for a
3-model chain, and only on a path that previously failed outright.

The prior handoff's diagnosis was right about the cause and is confirmed: instructor's
`max_retries` (already 2 everywhere) never engages, because its predicate is
`retry_if_exception_type((ValidationError, json.JSONDecodeError, AsyncValidationError,
ResponseParsingError))` and a `tool_use_failed` 400 is a `BadRequestError`. Hence
`Max retries exceeded. Total attempts: 1` in the logs.

`backend/agent/nodes/executor.py` needed one companion change. That node already had its
own per-model malformed-tool-call retry (`TOOL_CALL_RETRIES = 3`) and degrades to a
content-only message so the graph can still reach the Synthesizer. Its
`_MalformedToolCalls` exception embeds the original Groq text, so it would now match the
new signature and get retried all over again on every model — 3 models x 3 attempts
instead of 3. It therefore carries `llm_no_failover = True`, which `_failover_reason`
checks first. That is a general opt-out, not a special case for one class.

**Tests:** `tests/test_llm_config.py`, 8 tests, no network or API key — `resilient_call`
is driven with fake callables. They cover: first-model success; 404 and 429 advancing
immediately; malformed-tool-call retrying the SAME model first; falling over after one
same-model retry; the bounded worst case (`2 x len(chain)` then reraise); an unrelated
error (401) propagating after exactly one attempt; and the `llm_no_failover` opt-out.

### ⚠️ Measured per-model reliability — read this before touching FALLBACK_CHAINS

A chain reorder was **attempted and reverted** during this session. Recording it so
nobody repeats it:

The reasoning was: gold query `launch_005` failed with qwen emitting XML-style tool-call
syntax (`<tool_call><function=Recommendation><parameter=confidence>`) rather than JSON,
2/2 on back-to-back attempts — so drop qwen from the agent chain in favour of
`openai/gpt-oss-safeguard-20b`, which the executor already falls over to successfully.

**That was wrong.** A direct A/B against the *real* `Recommendation` schema showed the
opposite:

| model | 2-field toy schema | real `Recommendation` |
|---|---|---|
| `qwen/qwen3.8-27b` | OK | **OK** |
| `openai/gpt-oss-safeguard-20b` | OK | **FAIL** — `tool_use_failed` |
| `openai/gpt-oss-120b` (agent primary) | OK | **FAIL** on both probe attempts |

So the "replacement" was worse than the incumbent, and the *primary* model fails this
schema intermittently too. Three distinct flavours hide behind the one
`tool_use_failed` code:

1. almost-valid JSON — escaped quotes inside an already-quoted string
2. valid JSON, wrong shape — `evidence` objects with `source`/`description` instead of
   the schema's `snippet`/`relevance`
3. a different tool-call syntax entirely (the XML above)

**Every model fails this schema sometimes; none fails it always.** That is exactly why
the same-model retry is the right fix and why dropping any single model is not. The
reverted commit would have made things worse while looking like a fix.

**The generalisable lesson, and the reason the toy-vs-real table above matters:**
`scripts/doctor.py --probe` was asserting structured output against a 2-field `Verdict`
model. Every Groq model passes that. It is the 8-field `Recommendation`, with its nested
`evidence` list, that actually fails in production — so the probe was reporting all-clear
on models that could not serve a single real Synthesizer call. `--probe` now exercises
the **real** `Recommendation` schema, `SCHEMA_PROBE_ATTEMPTS = 2` times per model, and
names which flavour it hit.

Both probes are now **informational and never fail the run**: a rate limit says nothing
about capability, and the free tier's daily budget is routinely spent by one eval run, so
failing `doctor` on a 429 would make it useless in exactly the situation where you want
to run it. Schema flakiness is not actionable either — the output says so, in the report.

### ✅ Verified end-to-end — full judged run, 2026-09-17 late

`eval/reports/2026-09-17-postfix-judged.{md,jsonl}`. 30 queries, Haiku 4.5 judge.

**The retry fired and recovered a query that would previously have died.** Exactly one
agent-stage malformed tool call in 30 queries, on `returns_004`, and the failed
generation is worth seeing:

```
"confidence": 0. nine,
```

A numeral-word hybrid. Everything else in the payload was perfect — `"decision": "go"`,
full summary, four reasoning steps, two evidence entries, risks, next actions — and
three characters destroyed it. Then:

```
[llm_config] agent: openai/gpt-oss-120b is emitting malformed tool calls; retrying the same model (attempt 2).
```

`returns_004` came back `go` at confidence 0.92, correct, 27.3s. One same-model retry,
no failover, no degrade. That is flavour A behaving exactly as the fix assumes.

Note this is the *same quirk* as the baseline's `returns_005` failure (which was also
`"confidence": 0. nine`), so it is a recurring tic of `gpt-oss-120b` on this schema, not
a one-off. `returns_005` itself passed first try this run — consistent with the failure
being stochastic rather than query-specific.

**The Synthesizer degrade fired twice** (`improve_007`, `improve_009`) and both were
bucketed correctly by the new accounting rather than counted as answers.

### What the aggregates say: nothing, and that is correct

| metric | baseline (`full-judged`) | this run | read |
|---|---|---|---|
| decision accuracy, like-for-like (24 rows both decided) | 62.5% | 66.7% | **+1 row — noise, not claimed** |
| decision accuracy, headline | 60.0% | 56.7% | **not comparable** — see confound below |
| decision correctness (judge) | 0.572 | 0.540 | flat |
| evidence relevance | 0.545 | 0.536 | flat (nothing touched retrieval) |
| completeness | 0.876 | 0.872 | flat |
| anti-hallucination | 0.811 | 0.860 | up, not claimed |
| trajectory F1 / precision / recall | 0.773 / 0.865 / 0.750 | 0.781 / 0.877 / 0.762 | flat |
| latency p50 | 33.1s | 33.4s | flat |
| latency p95 | 48.6s | 60.4s | worse — rate-limit failovers, see below |
| no-decision rate | 3.3% | 16.7% | worse — budget, see below |

Everything is flat within noise, which is the **right** outcome: this session's changes
were reliability, not quality. Do not let a future reader mistake the anti-hallucination
bump or the +1 row for an effect.

### ⚠️ The confound, stated plainly

The last five queries (`improve_006`-`improve_010`) are **rate-limit casualties, not
agent failures** — 3 errors and 2 degrades — and they score as `decision_match=False`.
That alone accounts for the headline dropping below the baseline. `120b` and `20b` were
at their TPD cap, `safeguard-20b` too, so both chains walked to qwen and hit its
1000-output-tokens-per-minute ceiling.

Cause: two eval runs plus several `--probe` calls in one day. The baseline ran on a fresh
budget. So the honest claim is **not** "reliability improved" — it is "the failure modes
are now recovered or labelled instead of fatal". On the one class that was fixed, 1/1
recovered.

### ⚠️⚠️ The most important finding: this harness has a ~11-row noise floor

Across the 24 rows where both runs produced a real decision, **11 flipped — 6 fixed,
5 broke — while hedge errors stayed identical at 7 and 7.** Nothing in this session
touches decision logic, so that is pure run-to-run variance.

**Consequence: a single run cannot detect a change smaller than ~11 rows (~37%).** That
invalidates the way the planner plan below states its targets — its "+6 rows / +20
points" predictions sit *below* the noise floor. To measure those you need either
repeated runs of the same config, or a narrower primary metric that moves first
(per-query-type hedge-error count, tool recall, evidence count), with headline accuracy
as a secondary. Budget accordingly: at one full run per day, a repeated-runs design is
several days of wall-clock.

This also independently corroborates the planner diagnosis — identical trajectories
coin-flipping is exactly what a prompt-level contradiction produces.

### Live confirmation of the planner diagnosis

**Zero `go` decisions across all 10 launch queries**, where gold expects 2 — and both
(`launch_006`, `launch_009`) were answered `needs_more_data`. That is the `prompts.py`
contradiction made visible: `go` is unreachable for launch queries. Confidence was
0.60-0.62 on every hedge and 0.84-0.86 on both commits — the disjoint step function,
all of it above the dead 0.5 replan threshold.

### What is still unverified

The **Executor** degrade (`be38fec9`) is unit-tested (12 tests) but **still not
exercised end-to-end.** The 2026-09-20 run could not test it — nothing failed. That is
the good outcome and the annoying one: the path only runs when a model chain is
exhausted, and on a clean budget no chain was. It stays in the same position the retry
fix was in before its own run confirmed it.

To verify you would need it to actually fire, which means either catching a genuinely
exhausted budget, or forcing it — patch `resilient_call` to raise a `RateLimitError` for
one query and confirm the run completes with a degraded row instead of an error. The
log line to look for is `[executor] giving up on tool calls — provider capacity
exhausted`. Do **not** pipe an eval through `tail`; it buffers away exactly these lines.

---

## ✅ Run on the rebalanced gold set — 2026-09-20

`eval/reports/2026-09-20-goldv2-judged.{md,jsonl}`. 33 queries, Haiku 4.5 judge, budget
verified clean beforehand (all four models served 1500-token requests), so **unlike the
2026-09-17 post-fix run there is no rate-limited tail confounding it.**

**33/33 completed. Zero errors, zero degraded, 0.0% no-decision rate** — the first full
run this project has finished without losing a query.

| metric | 2026-09-17 post-fix | 2026-09-20 (33 rows) |
|---|---|---|
| decision accuracy — launch, scored | 60.0% vs **60.0%** floor | **69.2%** vs **46.2%** floor |
| decision accuracy — all types | 56.7% vs 76.7% floor | 66.7% vs 69.7% floor |
| error / degraded / no-decision | 10.0% / 2 / 16.7% | **0.0% / 0 / 0.0%** |
| trajectory precision / F1 / recall | 0.877 / 0.781 / 0.762 | 0.849 / 0.798 / 0.811 |
| judge: decision / evidence / hallu / complete | 0.540 / 0.536 / 0.860 / 0.872 | 0.603 / 0.548 / 0.824 / 0.870 |
| latency p50 / p95 | 33.4s / 60.4s | 35.5s / **53.9s** |

### ⚠️ The nine-point jump is the benchmark, not the agent

**The agent code was identical between these two runs.** Launch accuracy rose 60.0% →
69.2% because the *floor* fell 60.0% → 46.2% when three `no_go` rows were added. The
previous run sat exactly on its baseline — i.e. demonstrated no decision value at all.
Same behaviour; a benchmark that can now show it. Do not quote the delta as an
improvement, and do not let a future reader do so either.

### What the run DOES prove

**The three new `no_go` cases went 3/3 on first execution**, at 0.85-0.86 confidence,
each calling the tools that carry the evidence:

- `launch_011` — Amazon's own Fire TV Stick Lite already sits at this SKU's exact price
- `launch_012` — the 4K Max ships Wi-Fi 6E and its seeded top complaint is "Wi-Fi 6E underused"
- `launch_013` — `smart_speaker` is −17.1% YoY and saturated

`no_go` overall is **4/5**. This is the first real evidence about that capability; at 2
rows it was unmeasurable. Declining a bad idea is the hardest of the three decisions.

The one miss is the pre-existing `launch_007` (AirPods sport variant) answered `go`.
Worth recording because it **partially rehabilitates the old over-confidence story**:
over-commitment is real but rare — 2 cases against 8 hedges — so under-commitment is
still the dominant pattern, with `launch_007` now isolated instead of buried.

### A useful negative result

Repairing the four unwinnable gold rows did **not** move `evidence_relevance`: 0.545 →
0.548, flat. That is the expected outcome and it is evidence *for* the truncation
diagnosis, not against it — softening the themes made those rows winnable, it did not
make the agent better at them, because the 1500-char cap in `synthesizer.py:39-40` is
still dropping 3 of 5 review snippets. Per-row the four are 0.1→0.2, error→0.6, 0.4→0.1,
0.7→0.9: all inside the ~11-row noise floor, so read the aggregate, not the rows.

**The single highest-value remaining change is therefore raising that cap** (~175 extra
tokens per run, measured). It is the one item with a diagnosed mechanism and an
unmoved metric waiting to confirm it.

## Mobile audit — item #6 (audited 2026-09-17, NOT fixed)

**The premise this item was written on is wrong: mobile navigation works.**
`sidebar.tsx` is `hidden md:flex`, but the same file exports `MobileNav` (lines
100-140), a bottom tab bar gated `md:hidden`, rendered by
`app/dashboard/layout.tsx:23` with `pb-16 md:pb-0` reserving its space. Five of
six destinations are in the bar (`navItems.slice(0, 5)`); the sixth,
`/assistant`, is the "Ask AI" button in the top bar, which is not `md:`-gated.
Nobody is stranded. Do not "add mobile nav".

The real defects, ranked by what a reviewer notices first:

**P0**

1. **Tab bar overflows below 390px.** `sidebar.tsx:114-137` — five items, each
   `px-3` plus a `max-w-[60px]` label, ≈384px of min-content in a 375px
   viewport. `justify-around` cannot shrink below min-content, so the fifth tab
   clips on an iPhone SE / 13 mini and most 360px Androids. Fix: `flex py-2` on
   the `ul`, `min-w-0 flex-1` on each `li`, `w-full truncate text-center` on
   the label.
2. **Two tabs highlight at once.** `sidebar.tsx:119-120` — the mobile predicate
   is `pathname === item.href || (item.href === '/dashboard' && pathname.startsWith('/dashboard'))`,
   so on `/dashboard/reviews` both Dashboard and Review light up. The desktop
   sidebar has the exclusion list (lines 66-72); the mobile copy does not.
   Every mobile item is a leaf route, so `pathname === item.href` suffices.
3. **Labels truncate to an ambiguous pair** — `Conversa…` beside `Competito…`.
   Shorten the source strings for mobile rather than truncating.
4. **`min-h-screen` duplicated on four page roots** (`reviews:359`,
   `conversations:124`, `compare:268`, `brief:84`) inside a layout that is
   already `min-h-screen`, below a 60px top bar in a `pb-16` wrapper — so
   document height is ≥ `100vh + 124px` regardless of content and every
   sub-route rubber-bands. Fix: delete it from the four pages.

⚠️ **Do NOT apply gotcha #3's `h-screen overflow-hidden` to the dashboard
layout.** That pattern belongs to the fixed-height chat routes, which pair it
with `min-h-0` on both the column and `main`. `app/dashboard/layout.tsx:15` has
no `min-h-0`, so `h-screen overflow-hidden` would let `main` overflow and get
clipped with no scrollbar — everything below the fold unreachable. `min-h-screen`
on the layout is correct here; the duplication on the pages is the bug.

**P1** — reviews table crushes 6 columns into 343px while its `overflow-auto`
container stays inert because the table is `w-full` (fix: `min-w-[760px]`);
`quality-breakdown.tsx:277-284`'s fixed `w-24` value column starves the label
to ~84px; the conversations chart reserves a fixed `YAxis width={120}` out of
~303px; four `justify-between` header rows never stack; and **every
explanatory tooltip is unreachable on touch** — Radix tooltips do not open on
tap, and `phrase-clouds.tsx:116` literally says "Hover a chip to see the exact
phrase". The synthetic-data disclaimer on the competitor panel is tooltip-only,
which is the one caveat you most want read. `components/ui/popover.tsx` is
already vendored.

**Explicitly clean, do not spend time:** no un-prefixed multi-column grids
anywhere in scope (all `grid-cols-1` with `sm:`/`md:`/`lg:` escalation), and the
reviews list is bounded at `pageSize = 25`, so the 644KB payload is a network
cost, not a layout defect.

---

## Planner diagnosis — item #7 (analysed 2026-09-17, NOT fixed)

**The premise is inverted. The agent UNDER-commits; it is not over-confident.**
Do not tighten the launch rubric — that is what created the current problem.

Measured over `eval/reports/2026-09-17-full-judged.jsonl`:

| type | gold distribution | majority-class baseline | agent |
|---|---|---|---|
| launch | nmd 6, go 2, no_go 2 | 6/10 | **7/10 — the best type** |
| returns | go 9, nmd 1 | 9/10 | 6/10 |
| improve | go 8, nmd 2 | 8/10 | 5/10 |

Error taxonomy over 12 errors: **8 hedges** (`go→needs_more_data` ×7,
`no_go→needs_more_data` ×1), 3 over-commits, 1 crash. **Zero** launch rows
answered `go` against a non-`go` gold — the recorded failure pattern has no
instances left. Commit `b5b2e3ee` already fixed it and overshot: wrong-`go`s
went 5 → 0 and hedge errors 0 → 8.

⚠️ **Sobering context for any claim about this agent: a constant-`go` predictor
scored 19/30 = 63.3%, above the agent's 60.0%.**

✅ **Acted on 2026-09-17 (late).** Baselines are now computed from the gold set at
runtime and printed beside the accuracy in every report, so they cannot drift.
Two deeper problems surfaced while doing it: `go/no_go/needs_more_data` is
launch-decision vocabulary that degenerates on diagnostic queries (a three-entry
per-type lookup scored **76.7%**), and `no_go` had only 2 of 30 rows, so that
capability was unmeasurable. Fixed by scoring only `launch` in the headline
(`DECISION_SCORED_TYPES` in `eval/run_eval.py`) with returns/improve reported as
informational, and by adding three `no_go` cases. The gold set is now **33 rows**;
the launch baseline fell 60.0% → **46.2%**, and the all-rows floors are 57.6%
(constant) / 69.7% (per-type). Full audit note in `eval/README.md`.

**Root cause is a contradiction in `prompts.py`, not a tuning problem.** Line
229: "List what's missing even when the decision is `go`." Line 189-191: "If
`evidence_gaps` is non-empty, the decision MUST be `needs_more_data` — no
exceptions." Jointly unsatisfiable: **`go` is logically unreachable for launch
queries.** Worked Example 2 (line 274) then violates the rule it was just
given. `schemas.py:137-139` reinforces it through the field description. That is
why byte-identical trajectories coin-flip — `returns_002/003` hedge and
`returns_006/010` say `go` on the same evidence state.

Two independent code bugs found alongside:

- **`synthesizer.py:53` passes a mutated plan under a misleading label.** It
  renders `state["plan"]` as "PLANNER initial plan", but `executor.py:163-164`
  removes each tool as it is called, so the Synthesizer is shown a plan
  consisting of exactly the tools that never ran. That actively manufactures
  the "a planned tool didn't run" inference behind the improve hedges. Fix:
  add an `initial_plan` key written once by the planner.
- **The re-plan loop has never fired.** `REPLAN_CONFIDENCE_THRESHOLD = 0.5`
  (`graph.py:62`), and the minimum confidence observed across 76 runs in three
  reports is **0.52** — the synthesizer prompt anchors hedge confidence at 0.55.
  The whole re-plan mechanism is untested in practice. Found independently by
  two separate investigations.

Also: `MAX_TOOL_ITERATIONS = 8` is never hit (max observed 4), so stopping is
prompt-driven and prompt changes can work. And confidence carries no
information independent of the decision label — `go`→0.85 in 11/13 cases, and
the ranges are disjoint, so it is a step function of the label copied from the
worked examples.

**Sequencing that matters:** the hedge bias is load-bearing for launch (it earns
5 of launch's 7 correct answers), so de-hedge **per query type**, leaving launch
alone. `returns` gold has exactly one `needs_more_data` row and it is already
wrong, so de-hedging returns has zero downside on passing rows.

---

## Retrieval diagnosis — item #11 (analysed 2026-09-17, NOT fixed)

**Not a ranking problem.** The judge never once complains about ranking in 29
judged rows. The recorded interpretation ("weakly-relevant evidence, therefore
retrieval ranking") is unsupported.

**`synthesizer.py:39-40` truncates each tool result at 1500 chars, and
`review_qa`'s serialized payload measures 2019-2218 chars** — so the cut lands
~700 chars inside `sources`, and because `answer` serializes first, **3 of 5
review snippets are deleted before the Synthesizer ever sees them**, on
essentially every call. That is the score signature exactly: the prose answer
survives (completeness 0.876, anti-hallucination 0.811) while the citable
quotes do not (evidence_relevance 0.545). Raising the cap to 3000 costs ~175
tokens per run — measured, and `review_qa` is the only tool that exceeds it
(`competitor_search` 1197, `price_history` 949, `trend_signal` 439,
`predict_return_risk` 252).

**`Evidence.relevance` is self-reported by the LLM.** Nothing computes it;
`rag_chatbot.py:226` calls `similarity_search`, not
`similarity_search_with_score`, so the distance is discarded. Every value the
judge quoted lies in [0.90, 1.00], n=11. Worse, `judges.py:53` renders it into
the judge's prompt as `rel=0.90` and the judge **cites it as corroboration** — a
self-graded constant fed to the grader as retrieval confidence. Compute it or
drop it.

**`evidence_relevance` is also contaminated**: `judges.py:66-73` packs
`expected_decision`, `expected_tools` and free-text `notes` into the
EXPECTED_OUTPUT the dimension is graded against, so it correlates with
`decision_match` at **+0.708** — higher than with any evidence feature. It is a
blended evidence/tool-recall/decision metric, not an evidence metric.

The dominant real driver is tool recall: `actual_tools == ['review_qa']`
(n=8) averages **0.300** versus 0.638 for everything else. If those 8 merely
scored like the rest the aggregate goes 0.545 → 0.638 with no retrieval change
at all.

**Retire `FILTERED_FETCH_K` as a suspect** — measured, not guessed: at
`fetch_k=20` a rating-filtered query returns 3 docs, at 400 it returns 5, on
both the largest and smallest store. The 400 already fixes the starvation it
was written for.

**Chunk size goes last, and there is a landmine.** `tests/test_onnx_embeddings.py`
does NOT block a re-chunk — it re-embeds stored text and compares, so it guards
the embedding model, not the chunking, and a re-chunked index still passes at
cosine 1.000000. The actual hazard: `review_qa.py:44` calls
`asin_reviews_df(asin, limit=100)`, which yields ~200-250 chunks, while the
committed stores hold 1,617-5,797. **Any rebuild through the current tool path
silently produces a ~15x smaller index and nothing raises.** Fix that limit
first, and note the stores are git-tracked (~65MB), so a re-index is a large
binary commit that destroys the ability to A/B. Also pointless before the 1500
cap is raised: larger chunks make truncation worse, not better.

---

## Alternative pickup (product work) — Item #8: Competitor Compare auto-populate

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
2. **Groq free-tier limits are PER MODEL: 8000 TPM / 200,000 TPD / 1000 RPD**, not a single org-wide pool (the older note below reflects the previous scheme). Per-model buckets are why the stage split in [src/llm_config.py](src/llm_config.py) works: the planner, executor and review_qa paths draw on three independent limits. `python -m scripts.doctor` prints the bucket map and warns when two concurrent stages share one.
   - ⚠️ **Corrected 2026-09-17: the binding constraint is TPD (200k/model/day), which this note previously omitted.** TPM recovers in a minute and is mostly invisible; TPD does not, and **one 30-query eval run comes close to exhausting it.** Two runs in a day means the second one measures the rate limiter, not your change — errors show up as `Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199863`. RPD is never the problem (a 15-query run used ~40 of 1000). Budget your eval runs: **one full judged run per model per day.** Resets at UTC midnight = 8 PM EDT.
   - A single Copilot query costs ~4-8 calls across 2-3 models, so it is not cheap against a 200k/day cap. `--limit N` is the throttle.
3. **`min-h-screen` on layouts causes page-level scroll** when content is taller than viewport. Use `h-screen overflow-hidden` instead. Affects `/agent/layout.tsx`, `/chat/layout.tsx`, `/assistant/layout.tsx`.
4. **Groq decommissioned the entire Llama family (Sept 2026).** Both `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` now 404 with `model_not_found`, which broke every LLM path — and looked like "retrieval is broken" because the RAG chain 404s *after* retrieval succeeds. All model IDs now live in [src/llm_config.py](src/llm_config.py). Run `python -m scripts.doctor` to validate every pin against Groq's live catalog; it exits non-zero and names the env var to change.
5. **`/agent/query/mock` always streams the same canned TOZO returns scenario** regardless of input — by design, a development fixture. Live endpoint is `/agent/query`. The new `/assistant` page always calls live `/assistant/query`.
6. **Frontend uses `fetch` + `ReadableStream` for SSE**, not `EventSource`. Shared reader at `frontend/components/assistant/sse.ts`.
7. **`frontend/.env.local` is tracked-but-gitignored** (committed before gitignore). Local changes should NOT be committed (`git restore --staged` first). Production env lives in Vercel dashboard, not this file.
8. ~~**macOS dev:** `torch==2.1.0+cpu` is Linux-only, install plain `torch`.~~ **Moot — torch is no longer a dependency.** Embeddings run on onnxruntime (`src/onnx_embeddings.py`), so there is no torch pin, no `--extra-index-url`, and no platform-specific install step: `pip install -r requirements.txt` just works everywhere. `brew install libomp` for XGBoost still applies. New floor to know about: faiss-cpu >=1.13 ships `macosx_14_0_arm64` wheels only, so local dev needs macOS 14+.
9. **Sync function calls inside async SSE generators block the event loop.** In `/assistant/query`, `await asyncio.to_thread(review_qa, ...)` for the quick path. `loop.run_in_executor` deadlocked on FAISS init — `asyncio.to_thread` works.
10. **`.claude/worktrees/`** in repo root is internal Cursor / Claude Code worktree state. Always untracked. Don't `git add` it.
11. ✅ **FIXED — OpenMP segfault (SIGSEGV, exit 139). Root cause proven 2026-09-17.**
    Earlier notes had this as "could not reproduce, cause unproven" and blamed Cursor's
    sandbox. Both were wrong. It reproduces anywhere, deterministically, and has nothing
    to do with sandboxing.

    **Trigger:** run FAISS `similarity_search` and *then* XGBoost in the same process.
    `faiss/.dylibs/libomp.dylib`, `sklearn/.dylibs/libomp.dylib` and xgboost each bundle
    their own OpenMP runtime; the second initialisation kills the process. The crash is
    **silent** — no `OMP Error`, no traceback, just exit 139.

    **How it showed up:** the full 30-query eval died at query 11/30 on `returns_001`,
    the first gold query that calls `predict_return_risk`. Queries 1–10 only touched
    review_qa, so they passed. Same mechanism as the historical "uvicorn died after one
    request": any agent run that hits review_qa then predict_return_risk will do it.

    **Fix:** `os.environ.setdefault("OMP_NUM_THREADS", "1")` at the top of `app.py` and
    `eval/run_eval.py`, before faiss/xgboost/sklearn load. Deterministic either way —
    5/5 clean with it, 3/3 crashes without.

    ⚠️ **`KMP_DUPLICATE_LIB_OK=TRUE` does NOT fix this** (still exit 139), despite being
    the standard advice for duplicate-OpenMP problems. Don't reach for it. Capping the
    thread count is what works, and it costs nothing here: `IndexFlatL2` over a few
    thousand vectors is microseconds and the XGBoost model is 126KB.

    Minimal repro, if it ever needs re-testing: load a vectorstore, run three
    `similarity_search` calls, then `predict_return_risk` — crashes without the env var.

    ⚠️ **Addendum 2026-09-17: `pytest` was hitting this too, and the fix above did not
    cover it.** `app.py`'s `os.environ.setdefault` runs when conftest *imports* app,
    which is too late if a test module or a pytest plugin has already pulled in faiss.
    So bare `pytest` segfaulted mid-run on macOS — while CI stayed green, because the
    manylinux wheels link one shared libgomp instead of bundling `.dylibs`. That is why
    the handoff could claim a passing suite and a local run could still die.
    Now pinned at the top of `tests/conftest.py` as well (assigned, not `setdefault` —
    an inherited higher value would reintroduce the crash). Verified 3/3 clean runs with
    `env -u OMP_NUM_THREADS python -m pytest`. Suite is **27 tests in ~4s** (the old
    "13 tests in ~2s" figure predates both `test_onnx_embeddings.py` and
    `test_llm_config.py`).
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

## Eval baseline re-established (2026-09-17)

First judged 30-query run since 2026-05-18. Same gold set, so directly comparable:

| run | n | err | dec.acc | j:dec | j:evid | j:hal | j:comp |
|---|---|---|---|---|---|---|---|
| llama-4-scout (May) | 30 | 10 | 40.0% | 0.405 | 0.450 | 0.730 | 0.785 |
| gpt-oss-120b (2026-09-17) | 30 | **1** | **60.0%** | **0.572** | **0.545** | **0.811** | **0.876** |

Error rate 33.3% → 3.3%; every judge dimension up. Trajectory F1 is the one regression,
0.913 → 0.773 — but precision *rose* to 0.865 while recall fell to 0.750, i.e. the agent
now calls fewer, more targeted tools and misses some the gold set expects. Read that as a
gold-set/behaviour mismatch to investigate, not a straight quality loss.

**`evidence_relevance` (0.545) is the weakest dimension and it is real** — 0.60 on a
3-query smoke, 0.545 across all 30, lowest of the four in both this run and May's. With
completeness at 0.876 and anti-hallucination at 0.811, the pattern is thorough,
non-fabricated answers citing weakly-relevant evidence. That points at retrieval ranking
(`FILTERED_FETCH_K`, chunking, the rating filter), not the model or the prompts. Best
single lead for agent-quality work.

**34 executor failovers** fired during the run — `openai/gpt-oss-20b` saturates its
8000 TPM bucket almost immediately under back-to-back agent runs, and `resilient_call`
moved to `openai/gpt-oss-safeguard-20b` each time. Zero queries lost to rate limits,
versus the 429-driven failures that produced May's 33% error rate. The mechanism works;
just expect the primary executor bucket to be exhausted for most of any full run.

**The one failure** was `returns_005`: `tool_use_failed` — `gpt-oss-120b` emitted
malformed JSON for the `Recommendation` tool call and `InstructorRetryException` gave up.
Both such incidents this session logged `Total attempts: 1`, so **instructor retries are
not actually retrying**. ✅ **Fixed later the same day** — but note the guess in the
original sentence here ("setting `max_retries` would likely have saved this query") was
wrong twice over: `max_retries` was already 2 at every call site, and the failure is not
one instructor's predicate retries at all. See "Detail — `tool_use_failed`" above.

Results now persist incrementally (`_write_jsonl` after every query and every judge
result), so a crash or rate-limit wall no longer discards a 20-minute paid run — which is
exactly what happened on the first attempt at this eval.

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

# Preflight before ANY LLM work (standing rule)
python -m scripts.doctor
# ...and --probe to exercise the real Recommendation schema per model. Probes are
# informational: they never fail the run, and a `rate-limited` flavour means
# "inconclusive", not "broken".
python -m scripts.doctor --probe

# Before ANY live demo — backend latency, demo-ASIN hydration, live-vs-local
# commit (via the Render API), frontend, and the launchd warmup agent.
# Exit 0 = demo-ready.
scripts/predemo_check.sh

# Warmup pinger: one ping now, and the log the launchd agent writes
scripts/warmup_ping.sh
tail -5 ~/Library/Logs/listinglens-warmup.log
launchctl print "gui/$(id -u)/com.listinglens.warmup"

# Tests. `env -u OMP_NUM_THREADS` proves conftest's OpenMP pin is doing its job
# (without the pin this segfaults on macOS — gotcha #11).
env -u OMP_NUM_THREADS python -m pytest -q

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
1d388b75 docs(health): warn that /health's commit field lags the actual deploy
de26bbc8 docs(env): document the optional Render deploy-diagnostic vars
60bf64a1 feat(health): report the deployed commit so a failed build is detectable
f2e0443b fix(eval): stop the OpenMP segfault and persist results as they are produced
8122b7ed fix(eval): require deepeval 4 so the configured judge can actually run
d9a3ffd4 fix(eval): stop reporting a judge that never ran, and declare the judge SDK
9ac01c9f chore(deps): make requirements-agent.txt eval-only
aae66f5f test: pin ENV_MODE unconditionally so the suite cannot run in dev mode
4761f967 Merge Python 3.13 runtime alignment and ONNX embeddings
7682f04a fix(llm): centralize Groq model config and survive the Llama decommission
a1e8d4b2 fix(deps): align runtime on Python 3.13 and move embeddings off torch
e5e0440e feat: conversational customer-care analytics...   ← end of prior handoff
```

All pushed; CI green on every push (the repo's first successful Actions runs). `main` is
in sync with `origin/main` and `1d388b75` is live on Render.

---

## Session 2026-09-20 — the image audit, and a new repo

Everything below is committed and pushed. Two repos now:

| | | |
|---|---|---|
| [listinglens](https://github.com/Het415/listinglens) | public | 6 commits, `c5aabe80..7383048a` |
| [vislens](https://github.com/Het415/vislens) | public, NEW | 7 commits, CI green |

**What this session was.** `visual_retrieval_build_plan.md` proposed a two-repo visual
retrieval system. Discussed as a *product* rather than a portfolio line, and split: a
real image-audit feature, and a benchmark honest about being a benchmark. All vision
code went to `vislens` because torch cannot come back into this process
(`requirements.txt:36-53`) and this container peaks at 469.8/512 MiB. ListingLens holds
only a thin HTTP client, one tool, and the UI.

### What is built

**vislens** (223 tests, ruff clean, CI on every push, no secrets/network/GPU):
- 6 deterministic compliance checks with a `tier` system — only `rule_exact` and
  `measured` can drive a verdict
- hardened fetcher, 6 SSRF controls, 72 tests
- the audit service (`vislens.service.app:app`, port 8100)
- near-duplicate detection, calibrated: **dhash @ ≤8**, held-out P 1.000 / R 0.989
- ABO catalog: 145,671 products, 535,734 images, both leak invariants asserted

**listinglens**:
- `image_audit` as a sixth tool (thin HTTP client, degrades to `unavailable`)
- `ImageAuditCard` + `ImageUpload` on `/assistant`
- 6 new gold rows (4 positive, 2 negative), 96 tests
- the fabricated `FALLBACK_CHECKS` / `FALLBACK_RECOMMENDATIONS` deleted

### ⚠️ Findings that contradict the build plan

**1. "Split by `product_id`, never by image" is necessary and NOT sufficient.** Done
exactly as specified it still left **27,554 images spanning two splits, touching 40.3%
of rows** — ABO lists the same product across marketplaces with byte-identical assets,
so a product-level split passes its own check while the pixels cross freely. Fixed by
splitting connected components of the product-image graph, after pruning 70 boilerplate
images (23 of them attached to ~33,300 products each) that otherwise create a giant
component of 36.6%. Now 0.

**2. ABO's 147K does not survive the `en_US` filter.** Measured: 26,424 (17.9%) — smaller
than the fallback dataset the plan proposed as backup. Hence two tables, both counts
published. The `en_*` ladder reaches 122,734, a 4.7× difference that makes the mandated
scaling sweep informative.

**3. A prompt instruction is weaker than a data structure.** THE lesson of the session.
Three measured iterations before the agent stopped reporting advisory measurements as
violations — a per-check `tier` field mislabelled them, then separate `f`/`a` lists still
carrying "fail" statuses did not help (the model claimed "the background isn't pure
white" about rules never evaluated, and invented "14.44° deviation" for a 14.44:1 ratio),
then neutralising the status to "measured" still left "key rule failures" in the prose.
What worked was **deleting the data**: the payload now carries only findings the agent may
assert, advisory measurements are counted not enumerated.

**4. Three rules govern the MAIN image only.** White background, 85% occupancy, and
background marks. Secondary images are explicitly permitted lifestyle backgrounds, props
and text. Applying all three across a set fails a compliant lifestyle photo — observed on
B08XPWDSWW: the main image genuinely fails occupancy at 45.8% while five secondaries
produce identical-looking numbers that mean nothing.

**5. pHash lost to dHash**, which is not the conventional wisdom. A 20%-wide promo badge
moves exactly the low-frequency DCT coefficients pHash rests on (48% recall); dHash
compares gradient signs on a 9×8 thumbnail where a badge flips two bits (100%). The tiled
hash is the mirror image — perfect on badges, 22% on crops.

**6. The near-duplicate encoder is not justified.** dhash reaches AUC 1.0000 against hard
negatives, leaving no headroom for a CLIP embedding to demonstrate. Per the plan's own
pre-commitment, ship hashing only — no model to host, no 176 MB ONNX export, no RSS gate.

**7. Spark is cut.** 83 MB of gzipped JSON is one DuckDB query. Also: the trading repo's
PySpark is `local[*]` + a pandas UDF in a notebook, so describe it as local-mode rather
than letting it imply a cluster.

### Eval impact — read before comparing any run

| floor | 33 rows | 39 rows |
|---|---|---|
| launch-only (**the headline**) | 46.2% | **46.2% unchanged** |
| all-types, always-`go` | 57.6% | 64.1% |
| all-types, per-type lookup | 69.7% | **74.4%** |

All six new rows are `improve`/`returns`, so `DECISION_SCORED_TYPES` is untouched and the
headline stays comparable. The **informational all-types figure is not comparable** — its
floor rose 4.7 points, so identical behaviour scores further below it. Same confound as
the 60%→69.2% move, opposite direction. Details in `eval/README.md`.

Primary metric for the new rows is a **count**: `image_audit` on N of 4 positives and 0 of
2 negatives. First measurement, single runs: **2/2 positives tested, 2/2 negatives
correct**.

### Bugs caught by verifying rather than reading

- The card's first wiring passed the tool's outer wrapper where the inner audit was
  expected → `undefined.flatMap` took down the whole assistant page. Now guarded.
- `had_alpha` was set from the image *mode*, so every opaque RGBA PNG (i.e. every canvas
  export) warned spuriously. Now pixel-based.
- `binary_closing` defaults to `border_value=0`, eating the outermost rows of any product
  touching the frame edge → false `white_background` failures.
- A grey background made the whole image one component, so product-exclusion claimed the
  entire border band and reported `skipped` on the violation the check exists to catch.
- The SKU-mismatch finding had no distance gate → flagged 5 of 7 real images.
- `test_service_imports_no_llm_client_and_no_torch` inspected `sys.modules` in-process
  and had been passing for the wrong reason; now a subprocess.
- CI's first run caught `httpx2` undeclared — installed ad hoc locally, never in
  `pyproject.toml`.

### Commands

```bash
# vislens
cd ~/github/vislens && .venv/bin/pytest -q          # 223 tests, ~19s
.venv/bin/python -m uvicorn vislens.service.app:app --port 8100
.venv/bin/python -m scripts.build_catalog --subset 500   # local smoke, <5 min
.venv/bin/python -m scripts.calibrate_near_dup           # needs data/near_dup_set

# the three-process dev loop
# .claude/launch.json now has backend, frontend AND audit-service
```

### Not done

1. **Kaggle account + phone verification** — still the critical path for the training
   half, and still only a human can do it. Gates GPU access *and* notebook internet.
   Select `NvidiaTeslaT4` explicitly: the P100 no longer runs Kaggle's own torch
   (`sm_60` excluded, restore PR rejected).
2. **Shard packing** — 398K loose files would hit Kaggle's ~500-output cap, so they pack
   straight into WebDataset tars. `abo-images-small.tar` (3 GB) is downloaded and
   verified but deliberately not extracted.
3. **Encoder training** — B2/B3. Recommendation against the spec: initialize the image
   tower from CLIP's visual encoder, because ResNet-50 + MiniLM is set up to lose and the
   loss would be uninterpretable. Freeze the text tower and precompute its embeddings —
   that is what makes batch 256 fit a free T4 with true in-batch negatives and no MoCo
   queue. Mask false negatives (`product_id` or `title_hash` match) or the ceiling is
   silently capped. fp16 + `GradScaler` on `sm_75`, `logit_scale` clamped to `log(100)`,
   loss in fp32, or it NaNs hours into a headless commit.
4. **`VISLENS_URL`** needs setting wherever the audit service is deployed. The tool
   defaults to localhost and degrades cleanly until then.
5. **Render plan** — Starter at $7/mo removes spin-down but keeps 512 MB; 2 GB is ~$25.
6. `visual_retrieval_build_plan.md` is committed and **public**. It reads as a portfolio
   document ("Project A from the portfolio plan", "what this produces for the resume").
   `git rm --cached` it if that is not wanted — though it is already in public history.

## Session 2026-09-21 — shard packing, and two split bugs it exposed

All in **vislens**. ListingLens is untouched this session. Three commits, pushed,
CI green on `defd026` (both jobs):

| | |
|---|---|
| `fb3112e` | `feat(data): pack the ABO images into shards, and fix what the packer found` |
| `4652664` | `build(deps): install only what serves, and delete a 122 MB dependency nothing imports` |
| `defd026` | `feat(deploy): a Render blueprint for the audit service, and CORS for the real frontend` |

`4652664` came from a spun-off background task, not the main thread. It shares the
same working tree, so **stage by explicit path in vislens rather than `git add -A`**
if another task is running.

### What is built

**`scripts/pack_shards.py`** — the archive's 398,212 images, of which 392,324 are
packable, into **42 shards, 3.86 GB, ~30s**.
The source tar is never extracted: the plan comes from the catalog parquet first,
then one sequential pass copies bytes across. Bytes are copied, never re-encoded
(vislens `CLAUDE.md` §9 — a packer that resized to 224 would be a second preprocessing
definition, and the disagreement with the ONNX export would be silent).

Two roles, an image in exactly one of them, shards pure in split *and* role:

| series | samples | shards | size |
|---|---|---|---|
| `pairs-train` | 97,287 | 10 | 942 MB |
| `pairs-val` / `pairs-test` | 11,747 / 12,107 | 2 / 2 | 113 / 117 MB |
| `index-train` | 228,619 | 22 | 2,166 MB |
| `index-val` / `index-test` | 26,652 / 28,704 | 3 / 3 | 251 / 268 MB |

405,116 samples over 392,324 images. `pairs` is a separate series because it is
942 MB of a 3.86 GB corpus — one undivided series makes every epoch read the other
2.9 GB to train on none of it. A job that globs `pairs-train-*.tar` **cannot
physically read a val pixel**, which is stronger than filtering at load time.

`manifest.json` carries per-series counts, payload bytes, shard bytes and a
SHA-256 per shard. Tar headers use fixed mtime/ownership and USTAR, so a run
record can cite a shard set by hash.

**Deployment path for the audit service** — `render.yaml`, `.python-version` (3.11),
and CORS that admits the real frontend plus Vercel previews. Nothing is deployed
yet; this is the config, not the act.

vislens is now at **243 tests** (from 223).

### ⚠️ Findings that matter more than the code

**1. An invariant that reads the wrong table proves nothing.** This is the
session's lesson, and the companion to the last session's finding #3. The packer
re-asserts no-image-in-two-splits on the bytes it is about to write, and on the
first real run it found **five images heading 57 catalog rows (43 of them in
`pairs`) in two or three splits at once**. `catalog.main_image_path` comes
straight from the listings and never passes through the product-image edge table,
so pruning the generic images left those rows pointing at a dropped image — and,
because the prune also removed the edge that would have unioned those listings
into one component, each got its split assigned independently. Both existing
checks read `product_images`, where the offending edges were already gone, so
both reported **zero**. Fixed by dropping listings headed by a generic image,
plus a third invariant on `catalog.main_image_id`.

**2. ⚠️⚠️ The split was not reproducible, and no invariant could tell.**
`assign_splits` keyed each component on its union-find **root** — whichever member
arrived first — and the edge list comes out of an unordered DuckDB scan. Rebuilding
an unchanged archive moved whole components between splits: **train +118, val −214,
test +39**. Every leak check passed throughout, because components stayed intact
and only their labels moved.

**Consequence for any future comparison: a split-dependent number measured before
2026-09-21 is not comparable to one measured after.** Nothing has been trained
yet, so nothing is lost — but do not treat a pre-fix figure as a baseline.

The key is now the component's smallest `product_id`. Two consecutive full builds
now produce a byte-identical assignment over all 145,614 rows, and a test shuffles
the edge list 25 ways and demands one answer.

**3. The packer's own first version was not reproducible either, and the way it
failed is the interesting part.** Shard count, per-shard sample counts and
per-shard **sizes** all matched exactly; only the SHA-256s disagreed. `product_id`
is not unique in `pairs` (the same ASIN is listed per marketplace), so the sample
key carries an occurrence suffix from `row_number()`. **101 groups of rows tie on
the ordering key, 99 of them differing only in `title_lang` — and every `en_XX`
tag is five characters.** Identical lengths, different contents. The ordering now
covers every column that can distinguish two rows.

**4. `pip install .` breaks the audit service at its first request**, and the
build log looks healthy. Measured: the wheel has 17 entries and **no data files** —
hatch packages `src/vislens` while the thresholds live at the repo root. Both
modules resolve them with `Path(__file__).resolve().parents[3]`, which is the repo
root from a checkout and the interpreter's `lib/python3.11` from site-packages.
Verified both ways: importing the app succeeds from a non-editable install,
`load_rules()` then raises `FileNotFoundError`. **`render.yaml` must keep `-e`** —
the reasoning is written at the line so nobody tidies it away.

**5. Vercel is the wrong host for the audit service**, checked against its docs
rather than remembered: a **4.5 MB request body cap** against 12 files × 8 MB, a
Python runtime offering 3.12/3.13/3.14 but **not 3.11** (which this repo pins for
Kaggle parity), and no state between invocations for the bounded in-memory audit
store. The frontend stays on Vercel; the service belongs on a long-lived process.

**6. ⚠️ The image audit is live and broken in production right now.**
`NEXT_PUBLIC_VISLENS_URL` is unset, so the deployed bundle at
`listinglens.hetprajapati.me` carries `|| "http://localhost:8100"` — confirmed by
pulling the live chunk, not inferred. The page is https, so the browser blocks the
request as mixed content before it is sent. It fails cleanly (`ImageUpload` renders
"Could not reach the audit service — …") and the agent-side tool degrades to
`unavailable` by design, but every visitor who clicks the upload card gets an error.

Also worth knowing: `listinglens-kappa.vercel.app` now **404s**. Only the custom
domain resolves.

### Catalog counts moved

Both fixes together: catalog 145,671 → **145,614**, product_images 535,734 →
**535,602**, pairs 121,350 → **121,307**. 0.04% of rows, and they were the rows
putting the same pixels in two splits.

### Resolved from the previous session's "Not done"

- **#5 Render plan** — decided and written into `render.yaml`: free tier, with the
  32-81s cold start explicitly traded against the tool's 8s timeout.
- **#2 Shard packing** — done, above.
- **#4 `VISLENS_URL`** — still unset, but the blueprint and CORS now exist, so
  what remains is dashboard work rather than code.

### Commands

```bash
# vislens
cd ~/github/vislens && .venv/bin/pytest -q            # 243 tests, ~20s
uv venv --python 3.11 && uv pip install -e ".[dev,data]"   # note: dev,data

python -m scripts.build_catalog                       # full catalog rebuild
python -m scripts.pack_shards                          # 42 shards, ~30s
python -m scripts.pack_shards --roles pairs            # training set only, 0.9 GB
```

### Not done

1. **Kaggle account + phone verification** — unchanged, and still the critical
   path. Gates GPU access *and* notebook internet. Select `NvidiaTeslaT4`
   explicitly; the P100 no longer runs Kaggle's own torch.
2. **Deploy the audit service.** Create the Render service from the blueprint, set
   `VISLENS_URL` on ListingLens' Render service, set `NEXT_PUBLIC_VISLENS_URL` on
   its Vercel project — and **redeploy the frontend**, because `NEXT_PUBLIC_*` is
   inlined at build time.
3. **Encoder training (B2/B3)** — the shards it needs now exist, so this is
   blocked on Kaggle alone. The recommendation against the spec stands: initialize
   the image tower from CLIP's visual encoder, freeze the text tower and precompute
   its embeddings, mask false negatives on `product_id`/`title_hash`, fp16 +
   `GradScaler` on `sm_75`, `logit_scale` clamped to `log(100)`, loss in fp32.
4. **Ship the rule JSONs as package data** behind `importlib.resources`, so
   `pip install .` works and finding #4 stops being a comment in a yaml file.
5. **vislens is not `ruff format` clean repo-wide** — 11 files would be
   reformatted, 15 are clean. CI runs `ruff check` only, so this is latent; but
   `.pre-commit-config.yaml` declares the `ruff-format` hook and the hook is **not
   installed locally** (`.git/hooks/pre-commit` absent). Either run the formatter
   once across the repo or drop the hook, rather than leaving both half-true.
6. **CI action versions** — `actions/checkout@v4` and `actions/setup-python@v5` are
   being forced onto Node 24, and `ubuntu-latest` migrates to Ubuntu 26 on
   2026-10-19. Nothing broken today.
7. **`visual_retrieval_build_plan.md` is still committed and public**, and still
   reads as a portfolio document. Carried forward undecided from 2026-09-20:
   `git rm --cached` it if that is not wanted, though it is already in public
   history either way.
8. Unchanged from before: the cron-job.org warmup job (~2 min, `docs/WARMUP.md`),
   and the Executor degrade path is still unexercised because nothing has failed.

## How to start the next chat

> Read `HANDOFF.md` in the repo root, **starting at "Session 2026-09-21"**. Last
> session packed the ABO images into WebDataset shards in
> [vislens](https://github.com/Het415/vislens) and, in doing so, found two bugs in
> the train/val/test split that every existing check had passed. Three commits,
> pushed, CI green.
>
> **Carry forward two lessons, not one.** From 2026-09-20: a prompt instruction is
> weaker than a data structure — what stopped the agent misreporting advisory
> measurements was deleting them from its context, not instructing it better. From
> 2026-09-21: **an invariant that reads the wrong table proves nothing.** Two leak
> checks read `product_images` and reported zero while five images sat in two
> splits in `catalog`, and the split assignment was non-deterministic for months
> without a single check noticing, because components stayed intact and only their
> labels moved. Assert on the artifact you are about to ship, not on the table it
> came from.
>
> **One thing is waiting on a human and is still the critical path:** create a
> Kaggle account and complete phone verification. It gates GPU access and notebook
> internet, and nothing in the training half can start without it. Select
> `NvidiaTeslaT4` explicitly — the P100 no longer runs Kaggle's own PyTorch.
>
> **The shards now exist**, so encoder training (B2/B3) is blocked on Kaggle alone
> rather than on data prep. `data/shards/` holds 42 shards, 3.86 GB, reproducible
> and manifest-checksummed; `pairs-train-*.tar` is the contrastive set.
>
> **The other live item is a deploy, and it is mostly dashboard work.** The audit
> service has a `render.yaml` and CORS for the real frontend but is not deployed,
> so the upload card on `listinglens.hetprajapati.me` errors for every visitor
> today. Create the Render service, set `VISLENS_URL` and
> `NEXT_PUBLIC_VISLENS_URL`, then redeploy the frontend — the Vercel variable is
> inlined at build time, so setting it is not enough.
>
> Standing rules, all still true:
> - Before anything LLM-related, run `python -m scripts.doctor`.
> - **Groq hosts no vision model.** Verified 2026-09-20: 13 models, none
>   multimodal. For image work use a local pinned ONNX model.
> - Before quoting an eval number, confirm `.env` has `ANTHROPIC_API_KEY`.
> - **Budget one full eval run per day.** 200k tokens per model per day, rolling.
> - **Do not trust a single-run eval delta smaller than ~11 rows (~37%).**
> - **A split-dependent number from before 2026-09-21 is not comparable to one
>   after it.** The split was relabelled by the reproducibility fix.
> - In vislens, install `.[dev,data]` — the test suite imports duckdb, and the
>   default set no longer carries it.
> - In vislens, `render.yaml` must install with `-e`. A non-editable install
>   cannot find the rule thresholds.
> - Groq's free tier is the binding constraint on ListingLens. vislens has no such
>   constraint — its whole suite is deterministic, which is why it runs in CI.
> - Run `scripts/predemo_check.sh` before any demo.
> - To check what is deployed, ask the Render API, not `/health`.

*End of handoff.*
