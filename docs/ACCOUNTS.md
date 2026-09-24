# Accounts, saved reports and chats

Sign-in is optional. Anyone can analyze a product; an account only exists so a
seller can keep Copilot recommendations, executive briefs and assistant chats
across sessions.

- **Auth:** Better Auth in the Next.js app (`frontend/lib/auth.ts`), Google and
  GitHub sign-in, sessions in Postgres.
- **Storage:** Neon Postgres. `saved_reports` and `conversations`
  (`frontend/db/001_saved.sql`) reference `"user"(id) ON DELETE CASCADE`, so
  deleting an account deletes everything saved under it.
- **Routes:** `/api/me/reports`, `/api/me/reports/[id]`,
  `/api/me/conversations/[asin]`. Each handler checks the session itself and
  scopes every query by user; another user's row is a 404, never a 403.
- **The FastAPI backend is not involved.** It never sees a user or a cookie.

## Limits

| What | Limit | Why |
|---|---|---|
| Saved reports per user | 200 (409 past it) | Neon free-tier storage |
| Messages kept per chat | last 100 | same |
| Request body | 256 KB (413) | same; measured on actual bytes |

Saved payloads are `{"schema_version": 1, "data": ...}`. When the shape of a
Recommendation or Brief changes, bump `SAVED_SCHEMA_VERSION` in
`frontend/lib/saved.ts` and teach `savedView` the old version; anything it
doesn't recognise renders a plain fallback instead of crashing.

## Account linking

If Google and GitHub return the same email, they link to one user **only when
the provider reports the email verified and the existing user's email is
verified** (Better Auth defaults, pinned by `tests/auth-config.test.ts`). No
provider is trusted by name, so an unverified GitHub email can't take over a
Google-created account.

Manual check (needs real OAuth, so not in CI): sign in with Google, sign out,
sign in with GitHub using the same verified email, then in Neon:

```sql
SELECT u.email, count(a.*) FROM "user" u JOIN account a ON a."userId" = u.id GROUP BY u.email;
```

Expect one user with two accounts. A GitHub account whose email is unverified
must be refused with an `account not linked` error.

## One-time setup

1. **Neon:** create a project with `main` and `dev` branches. Copy the pooled
   and the direct (unpooled) connection string for each.
2. **Google Cloud:** OAuth consent screen, then one Web client with both
   redirect URIs:
   - `http://localhost:3000/api/auth/callback/google`
   - `https://listinglens.hetprajapati.me/api/auth/callback/google`

   **Publish the app out of "Testing"**, or only listed test users can sign in.
3. **GitHub:** two OAuth apps (GitHub allows one callback each):
   - `http://localhost:3000/api/auth/callback/github`
   - `https://listinglens.hetprajapati.me/api/auth/callback/github`
4. **Secrets:** `openssl rand -base64 32` for `BETTER_AUTH_SECRET`.
5. **Env:** names are in `frontend/.env.example`. Local values go in
   `frontend/.env.local`; production values in Vercel. Never commit either.
6. **Migrate** (uses `DATABASE_URL_UNPOOLED`; DDL doesn't go through the
   pooler). It runs Better Auth's migration first, then `001_saved.sql`, and is
   safe to re-run:

   ```bash
   cd frontend && npm run db:migrate
   ```

Vercel preview URLs and the `*.vercel.app` fallback can't sign in: they aren't
registered callbacks. That's expected.

## Tests

`frontend/tests/api-me.test.ts` runs the real handlers and SQL against a
throwaway Postgres, with only the session stubbed. It covers IDOR (another
user's report or chat is invisible and undeletable), the caps, size limits,
input validation and the delete cascade. CI runs it against a `postgres:17`
service container. Locally, point it at any disposable database (never
production):

```bash
cd frontend && DATABASE_URL_UNPOOLED=$TEST_DATABASE_URL npm run db:migrate && npm test
```

## The backend proxy

`/api/backend/*` forwards the browser's backend calls with the shared secret.
It is off by default (`NEXT_PUBLIC_API_MODE=direct`). The order for turning it
on, rotating the secret and rolling back is in `docs/INTERNAL_AUTH.md`, which
ships with the backend change.
