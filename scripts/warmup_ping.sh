#!/bin/bash
# Keep the Render free-tier backend awake AND its demo ASIN hydrated.
#
# Why this exists
# ---------------
# `.github/workflows/warmup.yml` declares `cron: '*/10 * * * *'` but GitHub
# throttles scheduled workflows on free accounts: measured gaps over
# 2026-09-14..16 were 137-326 min, median 241. Render free spins down after
# ~15 min idle, so the repo *looks* like it warms every 10 minutes while the
# service is actually asleep almost always (measured cold starts on /health:
# 32.7s and 81.3s).
#
# This script is the local half of the fix — run by launchd every 5 minutes
# (see the com.listinglens.warmup LaunchAgent), it fires while this Mac is
# awake, which is exactly the window a live demo happens in. The other half is
# an external pinger (cron-job.org) that covers the hours the Mac is off; see
# docs/WARMUP.md.
#
# POSTing /warmup rather than GETting /health matters: /health only keeps the
# process alive, while /warmup also preloads the demo ASIN's FAISS index, the
# ONNX embedding model and the compiled LangGraph, so the *first*
# /assistant/query is fast too.

set -uo pipefail

BACKEND_URL="${BACKEND_URL:-https://listinglens-api.onrender.com}"
# Matches frontend/lib/demo-config.ts — the TOZO T10 listing the dashboard
# loads when no ?asin= is given.
DEMO_ASIN="${DEMO_ASIN:-B08XPWDSWW}"
LOG_FILE="${WARMUP_LOG:-$HOME/Library/Logs/listinglens-warmup.log}"

mkdir -p "$(dirname "$LOG_FILE")"

# Keep the log bounded — this runs 288x/day forever. Truncate past ~256KB.
if [ -f "$LOG_FILE" ] && [ "$(wc -c <"$LOG_FILE")" -gt 262144 ]; then
  tail -c 131072 "$LOG_FILE" >"$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

# --max-time 120 survives an 81s cold boot (the worst measured). No --retry:
# launchd re-runs us in 5 minutes anyway, and a retry here would just stack
# requests onto an instance that is already busy booting.
#
# Captured via $(...) and split, NOT `read < <(curl ...)`: curl's -w output has
# no trailing newline, so `read` exits non-zero on EOF even though it assigned
# both fields, and an `|| fallback` on it silently reports every successful
# ping as unreachable.
result="$(
  curl -sS \
    --max-time 120 \
    -o /dev/null \
    -w '%{http_code} %{time_total}' \
    -X POST \
    -H 'content-type: application/json' \
    -d "{\"asin\":\"$DEMO_ASIN\"}" \
    "$BACKEND_URL/warmup" 2>/dev/null
)" || result=""
http_code="${result%% *}"
time_total="${result##* }"
[ -n "$http_code" ] || { http_code="000"; time_total="0"; }

# A cold start is the signal worth seeing in the log: >5s means this ping was
# the one that woke the instance, i.e. it had gone to sleep since the last tick.
state="warm"
case "$http_code" in
  000) state="UNREACHABLE" ;;
  2*)  awk -v t="$time_total" 'BEGIN{exit !(t>5)}' && state="COLD-START" ;;
  *)   state="HTTP-$http_code" ;;
esac

printf '%s  %s  %ss  %s\n' \
  "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$http_code" "$time_total" "$state" \
  >>"$LOG_FILE"

[ "${http_code:0:1}" = "2" ]
