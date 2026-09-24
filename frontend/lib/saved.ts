import { z } from 'zod'
import type { Recommendation } from '@/components/assistant/types'
import type { BriefResponse } from '@/lib/exportBrief'

// Storage rules for saved reports and chats. The route handlers stay thin; the
// rules live here so the tests can exercise them against a real Postgres.
//
// Every query is scoped by user_id. A row owned by someone else is
// indistinguishable from a missing one (404, never 403), so ids can't be probed.

/** Anything with pg's `query` — a Pool, a client, or a transaction. */
export interface Queryable {
  query<R extends object = Record<string, unknown>>(
    text: string,
    params?: unknown[],
  ): Promise<{ rows: R[]; rowCount: number | null }>
}

// Neon's free tier has limited storage; these keep one account from filling it.
export const MAX_REPORTS_PER_USER = 200
export const MAX_MESSAGES_PER_CONVERSATION = 100
export const MAX_BODY_BYTES = 256 * 1024

/** Bump when the shape of a saved `data` changes, and teach `savedView` the
 *  old version (or let it fall back). */
export const SAVED_SCHEMA_VERSION = 1

export const ASIN_RE = /^[A-Z0-9]{10}$/ // same as the backend's ASIN_PATTERN

export const ReportInput = z.object({
  kind: z.enum(['copilot', 'brief']),
  asin: z.string().regex(ASIN_RE),
  title: z.string().trim().min(1).max(200),
  question: z.string().max(2000).nullish(),
  data: z.record(z.unknown()),
})
export type ReportInput = z.infer<typeof ReportInput>

export const ConversationInput = z.object({
  messages: z.array(z.record(z.unknown())).max(1000),
})

export interface ReportSummary {
  id: string
  kind: 'copilot' | 'brief'
  asin: string
  title: string
  question: string | null
  created_at: string
}

export interface Report extends ReportSummary {
  payload: { schema_version?: unknown; data?: unknown }
}

export async function listReports(db: Queryable, userId: string): Promise<ReportSummary[]> {
  const { rows } = await db.query<ReportSummary>(
    `SELECT id, kind, asin, title, question, created_at
       FROM saved_reports WHERE user_id = $1
      ORDER BY created_at DESC`,
    [userId],
  )
  return rows
}

/** Returns the new id, or null when the user is at the cap. */
export async function createReport(
  db: Queryable,
  userId: string,
  input: ReportInput,
): Promise<string | null> {
  const payload = { schema_version: SAVED_SCHEMA_VERSION, data: input.data }
  // The cap check and the insert are one statement. Two saves racing at 199
  // can both land (201 rows); that's harmless for a storage guard.
  const { rows } = await db.query<{ id: string }>(
    `INSERT INTO saved_reports (user_id, kind, asin, title, question, payload)
     SELECT $1, $2, $3, $4, $5, $6
      WHERE (SELECT count(*) FROM saved_reports WHERE user_id = $1) < $7
     RETURNING id`,
    [userId, input.kind, input.asin, input.title, input.question ?? null, JSON.stringify(payload), MAX_REPORTS_PER_USER],
  )
  return rows[0]?.id ?? null
}

export async function getReport(db: Queryable, userId: string, id: string): Promise<Report | null> {
  if (!isUuid(id)) return null
  const { rows } = await db.query<Report>(
    `SELECT id, kind, asin, title, question, created_at, payload
       FROM saved_reports WHERE id = $1 AND user_id = $2`,
    [id, userId],
  )
  return rows[0] ?? null
}

export async function deleteReport(db: Queryable, userId: string, id: string): Promise<boolean> {
  if (!isUuid(id)) return false
  const { rowCount } = await db.query(
    `DELETE FROM saved_reports WHERE id = $1 AND user_id = $2`,
    [id, userId],
  )
  return (rowCount ?? 0) > 0
}

export async function getConversation(
  db: Queryable,
  userId: string,
  asin: string,
): Promise<unknown[] | null> {
  const { rows } = await db.query<{ messages: unknown[] }>(
    `SELECT messages FROM conversations WHERE user_id = $1 AND asin = $2`,
    [userId, asin],
  )
  return rows[0]?.messages ?? null
}

export async function putConversation(
  db: Queryable,
  userId: string,
  asin: string,
  messages: unknown[],
): Promise<void> {
  const kept = messages.slice(-MAX_MESSAGES_PER_CONVERSATION)
  await db.query(
    `INSERT INTO conversations (user_id, asin, messages, updated_at)
     VALUES ($1, $2, $3, now())
     ON CONFLICT (user_id, asin)
     DO UPDATE SET messages = EXCLUDED.messages, updated_at = now()`,
    [userId, asin, JSON.stringify(kept)],
  )
}

export async function deleteConversation(db: Queryable, userId: string, asin: string): Promise<void> {
  await db.query(`DELETE FROM conversations WHERE user_id = $1 AND asin = $2`, [userId, asin])
}

export const MAX_RECENT_PRODUCTS = 5

/** The products this user touched most recently: a chat they had or a report
 *  they saved, newest first. Feeds the product switcher's "Recent" group. */
export async function recentProducts(
  db: Queryable,
  userId: string,
  limit = MAX_RECENT_PRODUCTS,
): Promise<{ asin: string; last_active: string }[]> {
  const { rows } = await db.query<{ asin: string; last_active: string }>(
    `SELECT asin, max(at) AS last_active FROM (
       SELECT asin, updated_at AS at FROM conversations WHERE user_id = $1
       UNION ALL
       SELECT asin, created_at AS at FROM saved_reports WHERE user_id = $1
     ) activity
     GROUP BY asin
     ORDER BY last_active DESC
     LIMIT $2`,
    [userId, limit],
  )
  return rows
}

const UUID_RE =/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// A malformed id would make Postgres raise on the uuid cast; treat it as
// not-found instead of a 500.
function isUuid(id: string): boolean {
  return UUID_RE.test(id)
}

/** What the reports page should render for a saved report. Anything it
 *  doesn't recognise becomes a plain fallback view instead of crashing a card
 *  whose props have since changed. */
export type SavedView =
  | { type: 'copilot'; rec: Recommendation }
  | { type: 'brief'; brief: BriefResponse }
  | { type: 'fallback' }

export function savedView(report: Pick<Report, 'kind' | 'payload'>): SavedView {
  const { schema_version: version, data } = report.payload ?? {}
  if (version !== 1 || !data || typeof data !== 'object') return { type: 'fallback' }
  const d = data as Record<string, unknown>
  if (report.kind === 'copilot' && typeof d.decision === 'string' && typeof d.summary === 'string') {
    return { type: 'copilot', rec: d as unknown as Recommendation }
  }
  if (report.kind === 'brief' && d.brief && typeof d.brief === 'object') {
    return { type: 'brief', brief: d as unknown as BriefResponse }
  }
  return { type: 'fallback' }
}
