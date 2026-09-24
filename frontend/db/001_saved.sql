-- App tables for saved reports and chats. Run AFTER Better Auth's migration,
-- which creates "user" (scripts/migrate.mjs does both, in that order).
-- Idempotent, so re-running it is safe.
--
-- "user" is quoted everywhere: it is a reserved word in Postgres.

CREATE TABLE IF NOT EXISTS saved_reports (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     text        NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  kind        text        NOT NULL CHECK (kind IN ('copilot', 'brief')),
  asin        text        NOT NULL CHECK (asin ~ '^[A-Z0-9]{10}$'),
  title       text        NOT NULL,
  question    text,
  -- {"schema_version": N, "data": {...}}: the version is the shape of `data`
  -- for this kind, so an old report still opens after the UI types change.
  payload     jsonb       NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS saved_reports_user_created
  ON saved_reports (user_id, created_at DESC);

-- One chat history per user and product, mirroring the browser's
-- assistant_history_<asin> key.
CREATE TABLE IF NOT EXISTS conversations (
  user_id     text        NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  asin        text        NOT NULL CHECK (asin ~ '^[A-Z0-9]{10}$'),
  messages    jsonb       NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, asin)
);
