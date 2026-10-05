// Follow-up memory on the client: which turns a question carries, how a saved
// report becomes the backend's `pinned`, and that a chat holds one pin.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ASSISTANT_TURN_CHARS,
  USER_TURN_CHARS,
  buildHistory,
  clip,
  pinFromReport,
  toPinned,
  withPin,
} from '@/components/assistant/context'
import type { ChatMessage, PinnedReportRef, Recommendation } from '@/components/assistant/types'
import type { Report } from '@/lib/saved'

const ASIN = 'B08XPWDSWW'

const rec = (over: Partial<Recommendation> = {}): Recommendation => ({
  decision: 'go',
  confidence: 0.8,
  summary: 'Return risk is low.',
  reasoning_steps: [],
  evidence: [{ tool: 'review_qa', snippet: 'never sent', relevance: 0.9 }],
  risks: ['Battery complaints', 'Fit'],
  suggested_next_actions: ['Tag reviews by theme'],
  ...over,
})

const user = (content: string): ChatMessage => ({ role: 'user', content })
const quick = (content: string): ChatMessage => ({ role: 'assistant', content, sources: [] })

function report(over: Partial<Report> = {}): Report {
  return {
    id: '0b7c1f3e-4a55-4c0e-9d0a-2f1b3c4d5e6f',
    kind: 'copilot',
    asin: ASIN,
    title: 'TOZO T10: Go',
    question: 'Should I launch?',
    created_at: '2026-09-20T12:00:00.000Z',
    payload: { schema_version: 1, data: rec() },
    ...over,
  }
}

const briefData = {
  asin: ASIN,
  brief: {
    headline: 'Battery life drives returns.',
    situation: 'Returns rose 3 points.',
    key_findings: [{ metric: 'm', insight: 'never sent' }],
    top_risks: ['Battery', 'Fit'],
    recommended_actions: [
      { action: 'Ship a firmware fix', rationale: 'r', priority: 'high' },
      { action: 'Update the listing', rationale: 'r', priority: 'low' },
    ],
    confidence: 0.7,
  },
}

describe('buildHistory', () => {
  it('digests each turn: user text, a recommendation as decision + summary, a quick answer', () => {
    const messages: ChatMessage[] = [
      user('Why are returns spiking?'),
      { role: 'assistant', recommendation: rec() },
      user('What do 1-star reviews say?'),
      quick('Mostly battery failures.'),
    ]
    expect(buildHistory(messages)).toEqual([
      { role: 'user', content: 'Why are returns spiking?' },
      { role: 'assistant', content: 'go — Return risk is low.' },
      { role: 'user', content: 'What do 1-star reviews say?' },
      { role: 'assistant', content: 'Mostly battery failures.' },
    ])
  })

  it('skips the pin and errors, and a degraded verdict keeps only its summary', () => {
    const messages: ChatMessage[] = [
      { role: 'context', pinnedReport: pinFromReport(report()) },
      user('First?'),
      { role: 'assistant', error: 'rate limited', errorKind: 'rate_limited' },
      user('Second?'),
      { role: 'assistant', recommendation: rec({ degraded: true, decision: 'needs_more_data', summary: 'Partial.' }) },
    ]
    expect(buildHistory(messages)).toEqual([
      { role: 'user', content: 'First?' },
      { role: 'user', content: 'Second?' },
      { role: 'assistant', content: 'Partial.' },
    ])
  })

  it('keeps only the last three exchanges', () => {
    const messages = [1, 2, 3, 4].flatMap((i) => [user(`q${i}`), quick(`a${i}`)])
    const history = buildHistory(messages)
    expect(history.map((t) => t.content)).toEqual(['q2', 'a2', 'q3', 'a3', 'q4', 'a4'])
  })

  it('truncates like the server caps', () => {
    const [u, a] = buildHistory([user('u'.repeat(1000)), quick('a'.repeat(1000))])
    expect(Array.from(u.content)).toHaveLength(USER_TURN_CHARS)
    expect(Array.from(a.content)).toHaveLength(ASSISTANT_TURN_CHARS)
    expect(a.content.endsWith('…')).toBe(true)
  })

  it('is empty for a new chat, or one holding only a pin', () => {
    expect(buildHistory([])).toEqual([])
    expect(buildHistory([{ role: 'context', pinnedReport: pinFromReport(report()) }])).toEqual([])
  })
})

describe('clip', () => {
  it('counts code points, so a cut never splits an emoji', () => {
    const out = clip('😀'.repeat(10), 5)
    expect(Array.from(out)).toHaveLength(5)
    expect(out).toBe('😀😀😀😀…')
  })
})

describe('toPinned', () => {
  it('maps a copilot report to its decision, confidence, summary, risks and next actions', () => {
    expect(toPinned(pinFromReport(report()))).toEqual({
      id: '0b7c1f3e-4a55-4c0e-9d0a-2f1b3c4d5e6f',
      kind: 'copilot',
      asin: ASIN,
      title: 'TOZO T10: Go',
      decision: 'go',
      confidence: 0.8,
      summary: 'Return risk is low.',
      risks: ['Battery complaints', 'Fit'],
      next_actions: ['Tag reviews by theme'],
    })
  })

  it('maps a brief to its headline, situation, top risks and action texts', () => {
    const pin = pinFromReport(report({ kind: 'brief', payload: { schema_version: 1, data: briefData } }))
    expect(toPinned(pin)).toEqual({
      id: '0b7c1f3e-4a55-4c0e-9d0a-2f1b3c4d5e6f',
      kind: 'brief',
      asin: ASIN,
      title: 'TOZO T10: Go',
      headline: 'Battery life drives returns.',
      situation: 'Returns rose 3 points.',
      top_risks: ['Battery', 'Fit'],
      actions: ['Ship a firmware fix', 'Update the listing'],
    })
  })

  it('stays inside the request model bounds, so a long report never 422s', () => {
    // Saved data is untyped JSON, so a decision the type forbids can arrive.
    const long = rec({
      decision: 'd'.repeat(50) as Recommendation['decision'],
      confidence: 3,
      summary: 's'.repeat(5000),
      risks: Array(9).fill('r'.repeat(900)),
    })
    const out = toPinned(pinFromReport(report({ title: 't'.repeat(500), payload: { schema_version: 1, data: long } })))
    expect(out.title).toHaveLength(200)
    expect(out.decision).toHaveLength(32)
    expect(out.confidence).toBe(1)
    expect(out.summary).toHaveLength(1500)
    expect(out.risks).toHaveLength(5)
    expect(out.risks?.every((r) => r.length === 300)).toBe(true)
  })

  it('sends no fields it cannot read, rather than nulls', () => {
    const out = toPinned(pinFromReport(report({ payload: { schema_version: 1, data: { unexpected: true } } })))
    expect(out).toEqual({ id: expect.any(String), kind: 'copilot', asin: ASIN, title: 'TOZO T10: Go' })
    expect(toPinned(pinFromReport(report({ payload: {} })))).not.toHaveProperty('summary')
  })
})

describe('withPin', () => {
  it('keeps one pin, first, and replaces an older one without touching the turns', () => {
    const a: PinnedReportRef = pinFromReport(report({ id: 'a', title: 'A' }))
    const b: PinnedReportRef = pinFromReport(report({ id: 'b', title: 'B' }))
    const turns = [user('q'), quick('a')]
    const once = withPin(turns, a)
    const twice = withPin(once, b)
    expect(twice).toEqual([{ role: 'context', pinnedReport: b }, ...turns])
  })
})

// ── the store: pinReport, and what submitAssistant puts on the wire ──────────

describe('assistantStore', () => {
  const storage = new Map<string, string>()
  const bodies: Record<string, unknown>[] = []

  const sse = [
    'event: kind\ndata: {"value":"quick"}',
    'event: answer\ndata: {"content":"Battery failures.","sources":[]}',
    'event: done\ndata: {}',
  ].join('\n\n') + '\n\n'

  beforeEach(() => {
    storage.clear()
    bodies.length = 0
    vi.stubGlobal('window', globalThis)
    vi.stubGlobal('sessionStorage', {
      getItem: (k: string) => storage.get(k) ?? null,
      setItem: (k: string, v: string) => void storage.set(k, v),
      removeItem: (k: string) => void storage.delete(k),
      key: (i: number) => [...storage.keys()][i] ?? null,
      get length() {
        return storage.size
      },
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body)))
        return new Response(sse, { status: 200, headers: { 'content-type': 'text/event-stream' } })
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const saved = (asin: string) => JSON.parse(storage.get(`assistant_history_${asin}`) ?? '[]') as ChatMessage[]

  it('pinReport replaces an older pin and persists it at the start of the chat', async () => {
    const store = await import('@/components/assistant/assistantStore')
    const asin = 'B0PINTEST1'
    await store.submitAssistant(asin, 'Why returns?', 'quick')
    expect(await store.pinReport(asin, report({ id: 'a', asin, title: 'A' }))).toBe(true)
    expect(await store.pinReport(asin, report({ id: 'b', asin, title: 'B' }))).toBe(true)

    const messages = saved(asin)
    expect(messages.filter((m) => m.role === 'context')).toHaveLength(1)
    expect(messages[0]).toMatchObject({ role: 'context', pinnedReport: { id: 'b', title: 'B' } })
    expect(messages.slice(1).map((m) => m.role)).toEqual(['user', 'assistant'])

    store.unpinReport(asin)
    expect(saved(asin).some((m) => m.role === 'context')).toBe(false)
  })

  it('refuses a report about another product', async () => {
    const store = await import('@/components/assistant/assistantStore')
    expect(await store.pinReport('B0PINTEST2', report({ asin: ASIN }))).toBe(false)
    expect(saved('B0PINTEST2')).toEqual([])
  })

  it('a first question sends neither history nor pinned', async () => {
    const store = await import('@/components/assistant/assistantStore')
    await store.submitAssistant('B0PINTEST3', 'Why returns?', 'quick')
    expect(bodies[0]).toEqual({ asin: 'B0PINTEST3', query: 'Why returns?', mode: 'quick', audit_id: null })
  })

  it('a follow-up sends the earlier turns and the pin, not the new question', async () => {
    const store = await import('@/components/assistant/assistantStore')
    const asin = 'B0PINTEST4'
    await store.pinReport(asin, report({ id: 'p', asin }))
    await store.submitAssistant(asin, 'Why returns?', 'quick')
    await store.submitAssistant(asin, 'What about the 1-star ones?', 'quick')

    expect(bodies[0]).not.toHaveProperty('history')
    expect(bodies[0]).toMatchObject({ pinned: { id: 'p', asin, decision: 'go' } })
    expect(bodies[1]).toMatchObject({
      query: 'What about the 1-star ones?',
      history: [
        { role: 'user', content: 'Why returns?' },
        { role: 'assistant', content: 'Battery failures.' },
      ],
      pinned: { id: 'p', kind: 'copilot', asin, title: 'TOZO T10: Go' },
    })
  })

  it('Clear keeps the pin; only Unpin removes it', async () => {
    const store = await import('@/components/assistant/assistantStore')
    const asin = 'B0PINTEST5'
    await store.pinReport(asin, report({ id: 'p', asin }))
    await store.submitAssistant(asin, 'Why returns?', 'quick')
    store.clearAssistant(asin)
    expect(saved(asin).map((m) => m.role)).toEqual(['context'])
  })
})
