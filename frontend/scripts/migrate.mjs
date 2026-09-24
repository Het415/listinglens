// Creates the database schema: Better Auth's tables first, then ours.
//
//   npm run db:migrate
//
// Uses DATABASE_URL_UNPOOLED (Neon's DIRECT connection string). DDL through
// the pooler can fail or behave oddly; the app itself uses the pooled URL.
// Reads frontend/.env.local when present, otherwise the environment (CI).

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import pg from 'pg'
import { getMigrations } from 'better-auth/db/migration'

try {
  process.loadEnvFile(new URL('../.env.local', import.meta.url))
} catch {
  /* no .env.local — use the environment as-is */
}

const url = process.env.DATABASE_URL_UNPOOLED
if (!url) {
  console.error('[migrate] DATABASE_URL_UNPOOLED is not set')
  process.exit(1)
}

const pool = new pg.Pool({ connectionString: url, max: 1 })

try {
  // Only the database matters for the auth schema today. If a Better Auth
  // plugin that adds tables is ever enabled in lib/auth.ts, add it here too.
  const { toBeCreated, toBeAdded, runMigrations } = await getMigrations({ database: pool })
  const pending = toBeCreated.length + toBeAdded.length
  console.log(`[migrate] better-auth: ${pending ? `${pending} change(s)` : 'up to date'}`)
  if (pending) await runMigrations()

  const sql = await readFile(fileURLToPath(new URL('../db/001_saved.sql', import.meta.url)), 'utf8')
  await pool.query(sql)
  console.log('[migrate] 001_saved.sql applied')
} catch (err) {
  console.error('[migrate] failed:', err)
  process.exitCode = 1
} finally {
  await pool.end()
}
