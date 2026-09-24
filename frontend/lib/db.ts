import { Pool } from 'pg'

// One pool per server instance. On Vercel, DATABASE_URL must be Neon's POOLED
// connection string: every function instance opens its own pool, and the
// pooler is what keeps that from exhausting Postgres connections. Migrations
// use the direct URL instead (scripts/migrate.mjs).
//
// Cached on globalThis so Next's dev-mode hot reload doesn't leak a new pool
// per edit.
const g = globalThis as unknown as { __llPool?: Pool }

export function pool(): Pool {
  if (!g.__llPool) {
    const connectionString = process.env.DATABASE_URL
    if (!connectionString) throw new Error('DATABASE_URL is not set')
    g.__llPool = new Pool({ connectionString, max: 5 })
  }
  return g.__llPool
}
