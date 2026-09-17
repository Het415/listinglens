#!/bin/bash
# One command to run 2-3 minutes before a live demo.
#
# Answers the four questions that have actually gone wrong before:
#   1. Is the backend awake, and how slow is it right now?
#   2. Is the DEMO ASIN hydrated, or will the first agent query pay for FAISS
#      + the embedding model + a LangGraph compile?
#   3. Is the code that is LIVE the code I think is live? (Render API, not
#      /health -- /health's commit field lags a deploy; see health()'s docstring.)
#   4. Is the frontend serving?
#
# Exit 0 = demo-ready. Non-zero = read the output.

set -uo pipefail

BACKEND_URL="${BACKEND_URL:-https://listinglens-api.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://listinglens.hetprajapati.me}"
DEMO_ASIN="${DEMO_ASIN:-B08XPWDSWW}"

cd "$(dirname "$0")/.." || exit 1

bold=$(tput bold 2>/dev/null || true); dim=$(tput dim 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true); grn=$(tput setaf 2 2>/dev/null || true)
ylw=$(tput setaf 3 2>/dev/null || true); rst=$(tput sgr0 2>/dev/null || true)

fails=0
ok()   { printf '  [%sOK%s] %s\n' "$grn" "$rst" "$1"; }
warn() { printf '  [%sWARN%s] %s\n' "$ylw" "$rst" "$1"; }
bad()  { printf '  [%sFAIL%s] %s\n' "$red" "$rst" "$1"; fails=$((fails + 1)); }
head2() { printf '\n%s%s%s\n%s\n' "$bold" "$1" "$rst" "$(printf '%*s' ${#1} '' | tr ' ' -)"; }

# Read one var out of .env without `source`-ing it. Sourcing is fragile (a
# stray space after `=` makes zsh try to execute the secret as a command, and
# it lands in your shell history) -- and .env values here need no expansion.
env_get() {
  sed -n "s/^$1=[[:space:]]*//p" .env 2>/dev/null | head -1 | tr -d '"'"'"'\r'
}

printf '%sListingLens pre-demo check%s\n' "$bold" "$rst"

# ---------------------------------------------------------------- 1. backend
head2 "Backend (is it awake?)"
t0=$(curl -s -o /tmp/predemo-health.json -w '%{time_total} %{http_code}' \
  --max-time 120 "$BACKEND_URL/health" 2>/dev/null) || t0="0 000"
elapsed="${t0%% *}"; code="${t0##* }"

if [ "$code" != "200" ]; then
  bad "/health returned HTTP $code after ${elapsed}s"
elif awk -v t="$elapsed" 'BEGIN{exit !(t<1)}'; then
  ok "/health warm — ${elapsed}s"
elif awk -v t="$elapsed" 'BEGIN{exit !(t<5)}'; then
  ok "/health responding — ${elapsed}s"
else
  warn "/health took ${elapsed}s — this request WOKE the instance from sleep."
  printf '       %sThat is the cold start. It is now warm; the checks below\n' "$dim"
  printf '       will hydrate the demo ASIN. Re-run this to confirm.%s\n' "$rst"
fi

# ------------------------------------------------------------ 2. demo ASIN
head2 "Demo ASIN $DEMO_ASIN (will the first query be fast?)"
cached() {
  python3 -c '
import json, sys
try:    print(",".join(json.load(sys.stdin).get("cached_asins") or []))
except Exception: print("")
' </tmp/predemo-health.json 2>/dev/null
}

if [[ ",$(cached)," == *",$DEMO_ASIN,"* ]]; then
  ok "already cached — first agent query will be hot"
else
  warn "not cached; firing /warmup and waiting (up to 90s)"
  curl -s -o /dev/null --max-time 120 -X POST \
    -H 'content-type: application/json' -d "{\"asin\":\"$DEMO_ASIN\"}" \
    "$BACKEND_URL/warmup" 2>/dev/null
  hydrated=0
  for _ in $(seq 1 18); do
    sleep 5
    curl -s -o /tmp/predemo-health.json --max-time 30 "$BACKEND_URL/health" 2>/dev/null
    if [[ ",$(cached)," == *",$DEMO_ASIN,"* ]]; then hydrated=1; break; fi
  done
  if [ "$hydrated" = 1 ]; then
    ok "hydrated — first agent query will be hot"
  else
    bad "/warmup did not hydrate $DEMO_ASIN within 90s — check Render logs"
  fi
fi

# --------------------------------------------------------- 3. deployed commit
head2 "Deployed code (Render API — /health's commit field lags)"
api_key=$(env_get RENDER_API_KEY); svc=$(env_get RENDER_SERVICE_ID)
local_head=$(git rev-parse HEAD 2>/dev/null | cut -c1-12)

if [ -z "$api_key" ] || [ -z "$svc" ]; then
  warn "RENDER_API_KEY / RENDER_SERVICE_ID not in .env — skipping"
else
  live=$(curl -s --max-time 30 -H "Authorization: Bearer $api_key" \
    -H 'Accept: application/json' \
    "https://api.render.com/v1/services/$svc/deploys?limit=10" 2>/dev/null |
    python3 -c '
import json, sys
try:
    for d in json.load(sys.stdin):
        if d["deploy"].get("status") == "live":
            print(d["deploy"].get("commit", {}).get("id", "")[:12]); break
except Exception: pass
' 2>/dev/null)
  if [ -z "$live" ]; then
    warn "no deploy with status=live found (build in progress?)"
  elif [ "$live" = "$local_head" ]; then
    ok "live commit $live == local HEAD"
  else
    bad "live commit $live != local HEAD $local_head — push/deploy not finished"
  fi
fi

# Uncommitted work is not on Render, so the demo will not show it.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  warn "working tree is dirty — those changes are NOT in the live demo"
fi

# ------------------------------------------------------------- 4. frontend
head2 "Frontend"
fe=$(curl -s -o /dev/null -w '%{time_total} %{http_code}' --max-time 60 \
  "$FRONTEND_URL" 2>/dev/null) || fe="0 000"
fe_t="${fe%% *}"; fe_code="${fe##* }"
case "$fe_code" in
  200) ok "$FRONTEND_URL — ${fe_t}s" ;;
  000) bad "$FRONTEND_URL unreachable" ;;
  *)   bad "$FRONTEND_URL returned HTTP $fe_code" ;;
esac

# --------------------------------------------------------- 5. local pinger
head2 "Local warmup agent"
if launchctl print "gui/$(id -u)/com.listinglens.warmup" >/dev/null 2>&1; then
  last=$(tail -1 "$HOME/Library/Logs/listinglens-warmup.log" 2>/dev/null)
  ok "com.listinglens.warmup loaded${last:+ — last ping: $last}"
else
  warn "com.listinglens.warmup not loaded — see docs/WARMUP.md"
fi

# ------------------------------------------------------------------ verdict
if [ "$fails" -eq 0 ]; then
  printf '\n[%sOK%s] %sdemo-ready%s\n' "$grn" "$rst" "$bold" "$rst"
else
  printf '\n[%sFAIL%s] %s%d check(s) failed%s\n' "$red" "$rst" "$bold" "$fails" "$rst"
fi
exit $((fails > 0))
