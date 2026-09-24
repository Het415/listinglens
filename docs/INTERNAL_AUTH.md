# The proxy's shared secret

Every backend route is anonymous, and the API URL is in the frontend bundle for
anyone to read. The rate limits in `backend/http_limits.py` bound what a
stranger can spend, but the only legitimate caller is the site itself.

So the frontend calls the backend through a **Next.js server-side proxy**, and
the proxy adds a header the browser never sees:

```
X-Internal-Secret: <BACKEND_SHARED_SECRET>
X-Client-IP: <the visitor's address>
```

Once the secret is set on Render, `backend/internal_auth.py` answers any other
request with `401 {"detail": "unauthorized"}`. It never says whether the header
was missing or wrong.

**It is dormant until you set it.** With `BACKEND_SHARED_SECRET` unset the
check is off and nothing changes. Both env vars are read on every request, so
turning it on or off is an env change, never a code change.

## Env vars

| Where | Var | Value |
| --- | --- | --- |
| Render | `BACKEND_SHARED_SECRET` | The secret. Unset or empty = check off. |
| Render | `BACKEND_SHARED_SECRET_PREVIOUS` | The old secret, only while rotating. |
| Vercel | `BACKEND_SHARED_SECRET` | Same value. Server-only: **never** give it a `NEXT_PUBLIC_` prefix, or it ships in the bundle. |
| Vercel | `NEXT_PUBLIC_API_MODE` | `proxy` (via the secret-adding proxy) or `direct` (browser calls Render). |

Generate it with `openssl rand -hex 32`. Surrounding whitespace is stripped on
the Render side, since a dashboard paste often carries a trailing newline.

Vercel env vars are per environment. Set the secret for **Preview** too, or
preview deployments will get 401s once Render enforces it.

## What stays open, and why

`/`, `/health` and `/warmup` never need the secret (exact paths only;
`/health/` is refused). Their callers can't carry one, and none of them spends
LLM tokens:

- the Docker `HEALTHCHECK` (`curl /health`)
- the launchd pinger (`scripts/warmup_ping.sh`) and cron-job.org, both `POST /warmup`
- the GitHub Actions warmup cron (`.github/workflows/warmup.yml`)
- `scripts/predemo_check.sh` (`/health`, `/warmup`)

OPTIONS requests are open too, so a CORS preflight is never refused. Every other
path, including any route added later, needs the secret.

## Go-live, in this order

1. **Merge this (dormant).** `/health` reports `"internal_auth": "off"`.
2. **Vercel:** set `BACKEND_SHARED_SECRET` and `NEXT_PUBLIC_API_MODE=proxy`,
   then **redeploy** (`NEXT_PUBLIC_*` values are baked in at build time). The
   proxy now sends the secret; the backend ignores it for now, so the site
   keeps working.
3. **Render:** set `BACKEND_SHARED_SECRET` to the same value. Render restarts
   the service; the log shows `[internal_auth] enforced; open: /, /health, /warmup`.
4. **Verify:**

```bash
curl -s https://listinglens-api.onrender.com/health \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['internal_auth'])"
# enforced

# Only once the line above says "enforced": with the check off, this runs
# (and spends) a real query. GET /supported-asins is a zero-cost probe too.
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://listinglens-api.onrender.com/assistant/query \
  -H 'Content-Type: application/json' \
  -d '{"asin":"B08XPWDSWW","query":"hi","mode":"quick"}'
# 401
```

   Then open the site and run a query. If it fails, look in the Render log for
   `[internal_auth] refused ... secret header mismatch`: the two values differ.

## Rotating the secret

1. **Render:** move the old value to `BACKEND_SHARED_SECRET_PREVIOUS`, put the
   new one in `BACKEND_SHARED_SECRET`. Both are accepted now, so the live
   proxy, still sending the old one, keeps working.
2. **Vercel:** set `BACKEND_SHARED_SECRET` to the new value and redeploy.
3. **Render:** once the site works on the new deployment, clear
   `BACKEND_SHARED_SECRET_PREVIOUS`. Until you do, the startup log line ends
   with `(previous secret also accepted)` as a reminder.

## Rollback, in this order

1. **Render first:** unset `BACKEND_SHARED_SECRET`. `/health` goes back to
   `off`. The proxy keeps sending the secret, which is now ignored, so the site
   keeps working.
2. **Then Vercel:** set `NEXT_PUBLIC_API_MODE=direct` and redeploy.

**The reverse order takes the site down.** Switch Vercel to `direct` first and
the browser calls Render itself, and a browser can't hold the secret, so every
call except `/`, `/health` and `/warmup` is a 401 until Render's secret is
unset. Same logic as go-live: the side that *sends* the secret is always
switched on first and off last.

## The visitor's address

Behind the proxy, the TCP peer and `X-Forwarded-For` are Vercel's server, not
the visitor. So with a valid secret the rate limiter keys on `X-Client-IP`
instead (`_ip` in `app.py`). Without a valid secret that header is ignored, so
a direct caller can't pick a fresh rate-limit bucket per request.

If the proxy forgets `X-Client-IP`, or sends something that isn't a single IP
address, the backend falls back to the old resolution. Every visitor then
looks like one of a few Vercel addresses, so the per-visitor limits (20
requests a minute, 48 estimated LLM calls a day) **apply to the whole site**.
