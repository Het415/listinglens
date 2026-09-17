# Keeping the backend warm

The backend runs on Render's free tier, which **spins the instance down after
~15 minutes idle**. The first request after spin-down pays for a full Python
boot plus FAISS, the ONNX embedding model and a LangGraph compile. Measured
cold starts on `/health`: **32.7s and 81.3s**.

That is a demo-killer: the interviewer clicks the link and watches a spinner.

## Why the GitHub Actions cron does not solve this

`.github/workflows/warmup.yml` declares `cron: '*/10 * * * *'`, so the repo
*looks* like it warms every 10 minutes. **It does not.** GitHub throttles
scheduled workflows on free accounts. Measured gaps between actual runs,
2026-09-14 → 2026-09-16:

```
212, 241, 322, 294, 137, 163, 187, 293, 326, 299, 141   (minutes, median 241)
```

A ~4-hour median against a 15-minute spin-down means the instance is asleep
essentially always. Do not trust that cron. It is kept as a harmless backstop.

## The fix: two independent pingers

Both POST `/warmup` rather than GETting `/health`. That matters — `/health`
only keeps the process alive, while `/warmup` also preloads the demo ASIN's
FAISS index, the embedding model and the compiled graph, so the *first*
`/assistant/query` is fast too, not just the first page load. `/warmup` is
intentionally unauthenticated, side-effect-free, and returns in ~0.2s
(it hydrates in a background thread; the cache is populated within ~10s).

### 1. Local — installed, covers "my Mac is awake"

A launchd agent pings every 5 minutes while this Mac is awake. This is the
window a live demo actually happens in.

- Script: [`scripts/warmup_ping.sh`](../scripts/warmup_ping.sh)
- Agent: `~/Library/LaunchAgents/com.listinglens.warmup.plist` (not in the
  repo — it carries an absolute path to this checkout)
- Log: `~/Library/Logs/listinglens-warmup.log`, bounded to ~256KB

```bash
tail -5 ~/Library/Logs/listinglens-warmup.log
```

Each line is `<UTC timestamp>  <http code>  <seconds>  <state>`. `state` is
`warm` normally, and `COLD-START` when that ping took >5s — meaning the
instance had gone to sleep since the previous tick. A run of `COLD-START`
lines is the signal that the external pinger below has stopped working.

Manage it with:

```bash
launchctl print "gui/$(id -u)/com.listinglens.warmup"
```

To reinstall after moving the checkout, or to remove it:

```bash
launchctl bootout "gui/$(id -u)/com.listinglens.warmup"
```

### 2. External — YOU need to create this, ~2 minutes

Covers the hours the Mac is off, i.e. a link an interviewer opens the next
morning. Free tier is enough. Sign in at <https://cron-job.org> (or
UptimeRobot / Better Uptime — any of them works), create one job:

| Field | Value |
| --- | --- |
| Title | `ListingLens warmup` |
| URL | `https://listinglens-api.onrender.com/warmup` |
| Schedule | Every 5 minutes |
| Request method | `POST` |
| Request header | `Content-Type: application/json` |
| Request body | `{"asin":"B08XPWDSWW"}` |
| Timeout | 120s (needs to survive an 81s cold boot) |
| Treat redirects as success | off (there are none) |

Notes:

- `B08XPWDSWW` is the TOZO T10 demo ASIN, defined in
  `frontend/lib/demo-config.ts`. Keep the two in sync; a warmup for the wrong
  ASIN keeps the process alive but leaves the demo's first query cold.
- cron-job.org's free tier allows 1-minute granularity, so 5 minutes is well
  within it. UptimeRobot's free tier floor is 5 minutes — also fine, but it
  only sends GETs on the free plan, so `/warmup`'s body is dropped and you get
  process-alive-only warming. Prefer cron-job.org for that reason.

After creating it, confirm from the log that cold starts stop appearing
overnight — the local agent will report `warm` on its first ping of the day
if the external pinger is doing its job.

## Verify before any demo

Run this 2–3 minutes before you share the link, regardless of the pingers:

```bash
scripts/predemo_check.sh
```

Under 1s on `/health` means warm; 30s+ means that command is what woke it, so
wait for the script's second stage to report the demo ASIN cached.

## If you want certainty

Render **Starter ($7/mo) removes spin-down entirely** and makes all of the
above unnecessary. Worth one month around interview season.
