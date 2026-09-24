// Follow-up memory for /assistant: what a question carries about the chat so far.
//
// The backend used to receive only the new question, so "what about the 1-star
// ones?" meant nothing to it. Each request now also sends a digest of the last
// few turns (`history`) and, when the chat continues from a saved report, that
// report's structured fields (`pinned`). The server caps both again before any
// prompt sees them (backend/agent/context.py); the limits here match its
// request model (app.py), so a long chat or report never turns into a 422.
//
// Pure functions, no React and no storage, so they are tested directly.

import type { Report } from '@/lib/saved'
import type { ChatMessage, PinnedReportRef } from './types'

export interface HistoryTurn {
  role: 'user' | 'assistant'
  content: string
}

/** The backend's `PinnedReport` (app.py). */
export interface PinnedReport {
  id: string
  kind: 'copilot' | 'brief'
  asin: string
  title: string
  decision?: string
  confidence?: number
  summary?: string
  risks?: string[]
  next_actions?: string[]
  headline?: string
  situation?: string
  top_risks?: string[]
  actions?: string[]
}

// Same as the server's rendering caps, so nothing is sent that it would cut.
export const MAX_EXCHANGES = 3
export const USER_TURN_CHARS = 300
export const ASSISTANT_TURN_CHARS = 400

// The request model's per-field bounds.
const LIMITS = { id: 64, title: 200, decision: 32, text: 1500, headline: 300, item: 300, items: 5 }

/** Clip by code point, not UTF-16 unit: Python counts code points, and a cut
 *  through a surrogate pair would send a lone surrogate. */
export function clip(text: string, limit: number): string {
  const chars = Array.from(text)
  return chars.length <= limit ? text : chars.slice(0, limit - 1).join('') + '…'
}

export const isContext = (m: ChatMessage) => m.role === 'context'

/** A chat has turns when it has anything but a pin. */
export const hasTurns = (messages: ChatMessage[]) => messages.some((m) => !isContext(m))

export function pinnedOf(messages: ChatMessage[]): PinnedReportRef | null {
  return messages.find(isContext)?.pinnedReport ?? null
}

function assistantText(m: ChatMessage): string {
  const rec = m.recommendation
  if (rec) {
    // A degraded answer's decision is a placeholder, not a judgement.
    return rec.degraded ? rec.summary ?? '' : `${rec.decision} — ${rec.summary ?? ''}`
  }
  return m.content ?? ''
}

/** The last MAX_EXCHANGES exchanges (a question and what followed it), oldest
 *  first. Errors and the pin are not turns. */
export function buildHistory(messages: ChatMessage[]): HistoryTurn[] {
  const exchanges: HistoryTurn[][] = []
  for (const m of messages) {
    if (m.role === 'context' || m.error) continue
    const text = (m.role === 'user' ? m.content ?? '' : assistantText(m)).trim()
    if (!text) continue
    if (m.role === 'user' || exchanges.length === 0) exchanges.push([])
    exchanges[exchanges.length - 1].push(
      m.role === 'user'
        ? { role: 'user', content: clip(text, USER_TURN_CHARS) }
        : { role: 'assistant', content: clip(text, ASSISTANT_TURN_CHARS) },
    )
  }
  // The request model takes at most 6 turns.
  return exchanges.slice(-MAX_EXCHANGES).flat().slice(-2 * MAX_EXCHANGES)
}

const str = (v: unknown, limit: number): string | undefined =>
  typeof v === 'string' && v.trim() ? clip(v.trim(), limit) : undefined

function strs(v: unknown): string[] | undefined {
  if (!Array.isArray(v)) return undefined
  const out = v
    .map((x) => str(x, LIMITS.item))
    .filter((x): x is string => x !== undefined)
    .slice(0, LIMITS.items)
  return out.length ? out : undefined
}

const record = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' ? (v as Record<string, unknown>) : {}

/** Maps a pinned report's saved data to what the backend accepts. Unknown or
 *  malformed data just contributes no fields; the server then adds nothing. */
export function toPinned(report: PinnedReportRef): PinnedReport {
  const base: PinnedReport = {
    id: clip(report.id, LIMITS.id),
    kind: report.kind,
    asin: report.asin,
    title: clip(report.title, LIMITS.title),
  }
  const d = record(report.data)
  const fields: Partial<PinnedReport> =
    report.kind === 'copilot'
      ? {
          decision: str(d.decision, LIMITS.decision),
          confidence:
            typeof d.confidence === 'number' && Number.isFinite(d.confidence)
              ? Math.min(1, Math.max(0, d.confidence))
              : undefined,
          summary: str(d.summary, LIMITS.text),
          risks: strs(d.risks),
          next_actions: strs(d.suggested_next_actions),
        }
      : (() => {
          const brief = record(d.brief)
          return {
            headline: str(brief.headline, LIMITS.headline),
            situation: str(brief.situation, LIMITS.text),
            top_risks: strs(brief.top_risks),
            actions: strs(
              Array.isArray(brief.recommended_actions)
                ? brief.recommended_actions.map((a) => record(a).action)
                : undefined,
            ),
          }
        })()
  // Drop absent fields rather than send nulls the schema would have to allow.
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined) (base as unknown as Record<string, unknown>)[k] = v
  }
  return base
}

/** A saved report, as GET /api/me/reports/[id] returns it, as a pin. */
export function pinFromReport(report: Report): PinnedReportRef {
  return {
    id: report.id,
    kind: report.kind,
    asin: report.asin,
    title: report.title,
    savedAt: report.created_at,
    data: report.payload?.data ?? null,
  }
}

/** One pin per chat, always first: pinning again replaces the old one. */
export function withPin(messages: ChatMessage[], pin: PinnedReportRef): ChatMessage[] {
  return [{ role: 'context', pinnedReport: pin }, ...messages.filter((m) => !isContext(m))]
}

export function withoutPin(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((m) => !isContext(m))
}
