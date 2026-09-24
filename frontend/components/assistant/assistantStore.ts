'use client'

import { useCallback, useSyncExternalStore } from 'react'
import { apiUrl } from '@/lib/api'
import { readSSE } from './sse'
import type { ChatMessage, Recommendation, TraceStep } from './types'

export type Mode = 'quick' | 'copilot'

export interface AsinRunState {
  messages: ChatMessage[]
  trace: TraceStep[]
  loading: boolean
}

const EMPTY: AsinRunState = { messages: [], trace: [], loading: false }

// ── Module-scoped state ──────────────────────────────────────────────────────
// This map and the run loop below live at MODULE scope, not inside a React
// component. That's the whole point: client-side navigation tears down page
// components, but module state survives. So leaving /assistant mid-run does NOT
// abort the request, and coming back re-subscribes to the same live state —
// showing the streaming trace if it's still going, or the finished answer if it
// completed while the user was on another page.
const states = new Map<string, AsinRunState>()
const listeners = new Set<() => void>()

const historyKey = (asin: string) => `assistant_history_${asin}`

function emit() {
  for (const l of listeners) l()
}

function readHistory(asin: string): ChatMessage[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = sessionStorage.getItem(historyKey(asin))
    return raw ? (JSON.parse(raw) as ChatMessage[]) : []
  } catch {
    return []
  }
}

function writeLocal(asin: string, messages: ChatMessage[]) {
  if (typeof window === 'undefined') return
  try {
    if (messages.length === 0) sessionStorage.removeItem(historyKey(asin))
    else sessionStorage.setItem(historyKey(asin), JSON.stringify(messages))
  } catch {
    /* private-mode browsers can throw on write — ignore */
  }
}

function persist(asin: string, messages: ChatMessage[]) {
  writeLocal(asin, messages)
  pushRemote(asin, messages)
}

// ── Account sync ─────────────────────────────────────────────────────────────
// sessionStorage stays the source the UI reads from; a signed-in user's
// history is mirrored to /api/me/conversations so it outlives the tab. All of
// it is fire-and-forget: a failed sync must never break the chat itself.
// Signed-out users never touch the network here.
let syncUserId: string | null = null
const pulled = new Set<string>()

const remoteUrl = (asin: string) => `/api/me/conversations/${encodeURIComponent(asin)}`

function pushRemote(asin: string, messages: ChatMessage[]) {
  if (!syncUserId) return
  const req =
    messages.length === 0
      ? fetch(remoteUrl(asin), { method: 'DELETE' })
      : fetch(remoteUrl(asin), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages }),
        })
  req.catch(() => {})
}

async function fetchRemote(asin: string): Promise<ChatMessage[]> {
  const res = await fetch(remoteUrl(asin))
  if (!res.ok) return []
  const body = (await res.json()) as { messages?: ChatMessage[] }
  return Array.isArray(body.messages) ? body.messages : []
}

// A product whose history is empty in this tab adopts the saved copy — this is
// what brings a chat back after the tab was closed.
function pullIfEmpty(asin: string) {
  if (!syncUserId || pulled.has(asin)) return
  pulled.add(asin)
  const owner = syncUserId
  fetchRemote(asin)
    .then((remote) => {
      const cur = states.get(asin)
      // Only fill a history that is still empty and idle, for the same user.
      if (owner !== syncUserId || remote.length === 0 || !cur || cur.loading || cur.messages.length) return
      states.set(asin, { ...cur, messages: remote })
      writeLocal(asin, remote)
      emit()
    })
    .catch(() => pulled.delete(asin))
}

// On sign-in, chats started while signed out are uploaded once — but never
// over a history the account already has (from another device, say).
async function uploadLocalHistories() {
  if (typeof window === 'undefined' || !syncUserId) return
  const prefix = historyKey('')
  const asins: string[] = []
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i)
    if (key?.startsWith(prefix)) asins.push(key.slice(prefix.length))
  }
  for (const asin of asins) {
    const local = readHistory(asin)
    if (local.length === 0) continue
    try {
      if ((await fetchRemote(asin)).length === 0) pushRemote(asin, local)
    } catch {
      /* best-effort */
    }
  }
}

/** Called by <AccountSync/> whenever the session changes. */
export function setSyncUser(userId: string | null) {
  if (userId === syncUserId) return
  syncUserId = userId
  pulled.clear()
  if (!userId) return
  void uploadLocalHistories()
  for (const asin of states.keys()) pullIfEmpty(asin)
}

// Idempotent: seeds an ASIN's state from sessionStorage the first time it's
// requested, then returns the SAME object reference until something mutates it.
// Stable identity matters — useSyncExternalStore re-renders whenever the
// snapshot reference changes, so a fresh object every call would loop forever.
function hydrate(asin: string): AsinRunState {
  const existing = states.get(asin)
  if (existing) return existing
  const seeded: AsinRunState = { messages: readHistory(asin), trace: [], loading: false }
  states.set(asin, seeded)
  // hydrate runs inside render (getSnapshot), so the network pull is deferred.
  if (seeded.messages.length === 0) queueMicrotask(() => pullIfEmpty(asin))
  return seeded
}

export function clearAssistant(asin: string) {
  states.set(asin, { messages: [], trace: [], loading: false })
  persist(asin, [])
  emit()
}

export async function submitAssistant(
  asin: string,
  query: string,
  mode: Mode,
  /** An audit the browser already ran by uploading files straight to the audit
   *  service. Passed through so the agent's `image_audit` tool can reference
   *  the same audit — including which image the seller marked as the main one,
   *  which is what turns the main-image rules from measurements into
   *  verdicts. */
  auditId?: string | null,
) {
  const trimmed = query.trim()
  if (!trimmed) return

  const start = hydrate(asin)
  if (start.loading) return // one in-flight run per product at a time

  const withUser: ChatMessage[] = [...start.messages, { role: 'user', content: trimmed }]
  states.set(asin, { messages: withUser, trace: [], loading: true })
  persist(asin, withUser)
  emit()

  const pushTrace = (step: TraceStep) => {
    const cur = states.get(asin) ?? hydrate(asin)
    states.set(asin, { ...cur, trace: [...cur.trace, step] })
    emit()
  }

  let recommendation: Recommendation | null = null
  let quickAnswer: { content: string; sources: ChatMessage['sources'] } | null = null
  let errored: string | null = null
  let erroredKind: string | undefined

  try {
    const res = await fetch(apiUrl('/assistant/query'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asin, query: trimmed, mode, audit_id: auditId ?? null }),
    })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)

    for await (const { event, data } of readSSE(res)) {
      const now = Date.now()
      switch (event) {
        case 'node_started':
          pushTrace({ kind: 'node_started', node: data.node, label: data.label, ts: now })
          break
        case 'plan_ready':
          pushTrace({ kind: 'plan_ready', query_type: data.query_type, plan: data.plan, ts: now })
          break
        case 'tool_call':
          pushTrace({ kind: 'tool_call', tool: data.tool, args: data.args || {}, ts: now })
          break
        case 'tool_result':
          pushTrace({
            kind: 'tool_result',
            tool: data.tool,
            preview: data.result_preview || '',
            auditResult: data.audit,
            ts: now,
          })
          break
        case 'executor_thought':
          pushTrace({ kind: 'executor_thought', content: data.content, ts: now })
          break
        case 'replan':
          pushTrace({ kind: 'replan', reason: data.reason, ts: now })
          break
        case 'recommendation':
          recommendation = data as Recommendation
          break
        case 'answer':
          quickAnswer = { content: data?.content ?? '', sources: data?.sources ?? [] }
          break
        case 'error': {
          const message = data?.message || 'Unknown error'
          errored = message
          erroredKind = data?.kind
          pushTrace({ kind: 'error', message, ts: now })
          break
        }
        case 'done':
          pushTrace({ kind: 'done', ts: now })
          break
        // 'kind', 'started', 'node_completed' carry no trace rows
      }
    }
  } catch (e: unknown) {
    errored = e instanceof Error ? e.message : 'Network failure — is the backend running?'
    erroredKind = 'network'
  }

  // Finalize. This runs whether or not the user is still on the page: we mutate
  // module state + sessionStorage directly, so the answer is already waiting
  // when they navigate back.
  const cur = states.get(asin) ?? hydrate(asin)
  const answer: ChatMessage = errored
    ? { role: 'assistant', error: errored, errorKind: erroredKind }
    : recommendation
      ? { role: 'assistant', recommendation }
      : quickAnswer
        ? { role: 'assistant', content: quickAnswer.content, sources: quickAnswer.sources }
        : { role: 'assistant', error: 'Assistant finished without a result' }

  const finalMessages = [...cur.messages, answer]
  states.set(asin, { messages: finalMessages, trace: cur.trace, loading: false })
  persist(asin, finalMessages)
  emit()
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

// React binding. Returns the live state for one ASIN and re-renders the caller
// whenever that ASIN's run advances — from any page, including after a remount.
export function useAssistant(asin: string): AsinRunState {
  const getSnapshot = useCallback(() => hydrate(asin), [asin])
  const getServerSnapshot = useCallback(() => EMPTY, [])
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
