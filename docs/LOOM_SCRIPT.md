# 90-Second Loom Script — ListingLens Copilot

> Recording target: 90 seconds. 10-second blocks. Practice 3-5 takes. Record at 1400×900 in a chrome window with one tab and no notifications.

## Setup checklist (before hitting record)

- [ ] Browser zoomed to 100%, full-screen the Loom recorder
- [ ] Open [https://listinglens-kappa.vercel.app/agent?asin=B08XPWDSWW](https://listinglens-kappa.vercel.app/agent?asin=B08XPWDSWW)
- [ ] In a second tab, open the GitHub repo: [https://github.com/Het415/listinglens](https://github.com/Het415/listinglens)
- [ ] In a third tab, open the eval report: [eval/reports/2026-05-16-full.md](https://github.com/Het415/listinglens/blob/main/eval/reports/2026-05-16-full.md)
- [ ] Mute notifications, Do Not Disturb on
- [ ] Test mic level (Loom shows a meter)
- [ ] Have the demo query memorized: "Why are returns spiking on this product?"

---

## The script (90 seconds total)

### 0:00 – 0:10 — Hook + problem (10s)

> "Amazon sellers ask questions like 'Why are my returns spiking?' or 'Should I launch this variant?' Today they juggle five tools and gut feel. I built an AI agent that does the research for them."

*[On camera: starting frame is the /agent page, ASIN dropdown showing TOZO T10.]*

### 0:10 – 0:30 — The demo (20s, the money shot)

*[Click the sample query "Why are returns spiking?". The trace panel on the right starts animating.]*

> "The agent has five tools. Watch the trace on the right. **Planner** — classifies the query and picks tools. **Executor** — runs predict_return_risk, then review_qa. **Synthesizer** — writes the final recommendation."

*[Let the trace finish so the GO recommendation with 82% confidence renders.]*

> "**Three converging issues — return-risk model says HIGH, 1-star reviewers cite poor sound quality and customer service.** Three risks, three concrete next actions. Evidence cited per tool."

### 0:30 – 0:55 — The eval (the differentiator, 25s)

*[Cut to the eval report tab — `eval/reports/2026-05-16-full.md`.]*

> "I evaluated the agent honestly. 30 hand-crafted gold queries. LLM-as-judge with Claude Haiku — different model family than the Llama agent to avoid bias. Plus trajectory F1 — does the agent call the *right tools* in the *right order*."

*[Highlight the trajectory F1 row: 0.85 (precision 0.92, recall 0.82).]*

> "Trajectory F1 of 0.85. The Planner picks the right tools reliably. Decision accuracy is moderate — 57% — because the agent over-commits on launch decisions. The eval surfaces this; the next prompt iteration fixes it. That's the development loop."

### 0:55 – 1:20 — Architecture (25s)

*[Cut to the GitHub repo's README — the architecture diagram section.]*

> "Stack: LangGraph v1 for the state machine. MCP for the tool protocol. instructor and Pydantic for guaranteed structured output. Two of the five tools wrap my v1 RAG and XGBoost return-risk classifier — the agent extends the project, doesn't replace it."

*[Scroll to the "What I'd do next" section.]*

> "The README also has what I'd build next — multi-turn memory, self-critique, fine-tuned planner, scaling to a managed vector DB when there's a reason to. Showing judgment matters."

### 1:20 – 1:30 — Close (10s)

*[Back to the /agent page.]*

> "Live demo, full source, and the eval methodology are linked in the description. Thanks for watching."

*[Cut.]*

---

## Recording notes

- **Pace:** practice once at slow pace, then a take at ~85% speed. You'll feel like you're rushing; the recording will feel normal.
- **No throat-clearing intro.** Loom thumbnails autoplay the first 3 seconds — start with the pitch, not "hi, my name is..."
- **Mouse cursor:** large enough to track easily. Loom has a setting.
- **One take or two takes max** — perfectionism kills demos. The eval section is the most important; if anything's rough, it's fine elsewhere.
- **Caption it on Loom** after recording — accessibility + autoplay-mute users.

---

## After recording

- Paste the Loom URL into [README.md](../README.md) where it says *"Loom walkthrough (90s): TBD"*.
- Drop the link in the LinkedIn post (see [LINKEDIN_POST.md](LINKEDIN_POST.md)).
- Add to your resume's project entry as "90-second video walkthrough: <link>".
