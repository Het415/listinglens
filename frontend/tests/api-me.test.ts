// Route-level tests for /api/me/* against a real Postgres.
//
//   TEST_DATABASE_URL=postgres://... npm run db:migrate   (with DATABASE_URL_UNPOOLED set to the same URL)
//   TEST_DATABASE_URL=postgres://... npm test
//
// The session is stubbed (real OAuth can't run in a test); everything below
// it — the handlers, SQL, user scoping, caps — is the production code.

import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const TEST_DB = process.env.TEST_DATABASE_URL
if (process.env.CI && !TEST_DB) throw new Error('TEST_DATABASE_URL must be set in CI')
if (TEST_DB) process.env.DATABASE_URL = TEST_DB

const session = vi.hoisted(() => ({ userId: null as string | null }))
vi.mock('@/lib/session', () => ({ currentUserId: async () => session.userId }))

const A = 'test-user-a'
const B = 'test-user-b'
const ASIN = 'B08XPWDSWW'

const copilotReport = {
  kind: 'copilot',
  asin: ASIN,
  title: 'Test product: Go',
  question: 'Should I launch?',
  data: { decision: 'go', confidence: 0.8, summary: 'Looks good.', reasoning_steps: [], evidence: [], risks: [], suggested_next_actions: [] },
}

function post(url: string, body: unknown) {
  return new Request(url, { method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body) })
}
function put(url: string, body: unknown) {
  return new Request(url, { method: 'PUT', body: JSON.stringify(body) })
}
const req = (url: string) => new Request(url)
const idCtx = (id: string) => ({ params: Promise.resolve({ id }) })
const asinCtx = (asin: string) => ({ params: Promise.resolve({ asin }) })

describe.skipIf(!TEST_DB)('/api/me routes (real Postgres)', async () => {
  const reports = await import('@/app/api/me/reports/route')
  const report = await import('@/app/api/me/reports/[id]/route')
  const convo = await import('@/app/api/me/conversations/[asin]/route')
  const recent = await import('@/app/api/me/recent-products/route')
  const { pool } = await import('@/lib/db')
  const { MAX_REPORTS_PER_USER, MAX_MESSAGES_PER_CONVERSATION } = await import('@/lib/saved')

  beforeAll(async () => {
    await pool().query(
      `INSERT INTO "user" (id, name, email, "emailVerified") VALUES
         ($1, 'User A', 'a@test.invalid', true), ($2, 'User B', 'b@test.invalid', true)
       ON CONFLICT (id) DO NOTHING`,
      [A, B],
    )
  })

  beforeEach(async () => {
    session.userId = null
    await pool().query(`DELETE FROM saved_reports WHERE user_id = ANY($1)`, [[A, B]])
    await pool().query(`DELETE FROM conversations WHERE user_id = ANY($1)`, [[A, B]])
  })

  afterAll(async () => {
    await pool().query(`DELETE FROM "user" WHERE id = ANY($1)`, [[A, B]])
    await pool().end()
  })

  async function saveAs(user: string) {
    session.userId = user
    const res = await reports.POST(post('http://t/api/me/reports', copilotReport))
    expect(res.status).toBe(201)
    return ((await res.json()) as { id: string }).id
  }

  it('rejects every route without a session', async () => {
    const fakeId = '00000000-0000-4000-8000-000000000000'
    expect((await reports.GET()).status).toBe(401)
    expect((await reports.POST(post('http://t', copilotReport))).status).toBe(401)
    expect((await report.GET(req('http://t'), idCtx(fakeId))).status).toBe(401)
    expect((await report.DELETE(req('http://t'), idCtx(fakeId))).status).toBe(401)
    expect((await convo.GET(req('http://t'), asinCtx(ASIN))).status).toBe(401)
    expect((await convo.PUT(put('http://t', { messages: [] }), asinCtx(ASIN))).status).toBe(401)
  })

  it('saves, lists, opens and deletes a report for its owner', async () => {
    const id = await saveAs(A)
    const list = (await (await reports.GET()).json()) as { reports: { id: string }[] }
    expect(list.reports.map((r) => r.id)).toEqual([id])

    const opened = (await (await report.GET(req('http://t'), idCtx(id))).json()) as {
      report: { payload: { schema_version: number; data: { decision: string } } }
    }
    expect(opened.report.payload.schema_version).toBe(1)
    expect(opened.report.payload.data.decision).toBe('go')

    expect((await report.DELETE(req('http://t'), idCtx(id))).status).toBe(204)
    expect((await report.GET(req('http://t'), idCtx(id))).status).toBe(404)
  })

  it("IDOR: another user can't read, list or delete a report (404, row survives)", async () => {
    const id = await saveAs(A)

    session.userId = B
    expect((await report.GET(req('http://t'), idCtx(id))).status).toBe(404)
    expect((await report.DELETE(req('http://t'), idCtx(id))).status).toBe(404)
    const listB = (await (await reports.GET()).json()) as { reports: unknown[] }
    expect(listB.reports).toEqual([])

    const { rows } = await pool().query(`SELECT count(*)::int AS n FROM saved_reports WHERE id = $1`, [id])
    expect(rows[0].n).toBe(1)
  })

  it("IDOR: another user's conversation for the same product is invisible", async () => {
    session.userId = A
    const msgs = [{ role: 'user', content: 'secret question from A' }]
    expect((await convo.PUT(put('http://t', { messages: msgs }), asinCtx(ASIN))).status).toBe(204)

    session.userId = B
    const got = (await (await convo.GET(req('http://t'), asinCtx(ASIN))).json()) as { messages: unknown[] }
    expect(got.messages).toEqual([])
    // B deleting "their" conversation doesn't touch A's.
    await convo.DELETE(req('http://t'), asinCtx(ASIN))

    session.userId = A
    const mine = (await (await convo.GET(req('http://t'), asinCtx(ASIN))).json()) as { messages: unknown[] }
    expect(mine.messages).toEqual(msgs)
  })

  it('returns 409 once the per-user report cap is reached', async () => {
    // Fill to the cap directly; 200 round-trips through the handler add nothing.
    await pool().query(
      `INSERT INTO saved_reports (user_id, kind, asin, title, payload)
       SELECT $1, 'copilot', $2, 'filler', '{"schema_version":1,"data":{}}'::jsonb
         FROM generate_series(1, $3)`,
      [A, ASIN, MAX_REPORTS_PER_USER],
    )
    session.userId = A
    const res = await reports.POST(post('http://t', copilotReport))
    expect(res.status).toBe(409)
    // Another user is unaffected by A's cap.
    expect((await reports.POST((session.userId = B, post('http://t', copilotReport)))).status).toBe(201)
  })

  it('returns 413 for a body over 256 KB, before parsing it', async () => {
    session.userId = A
    const big = { ...copilotReport, data: { ...copilotReport.data, summary: 'x'.repeat(300 * 1024) } }
    expect((await reports.POST(post('http://t', big))).status).toBe(413)
    expect((await convo.PUT(put('http://t', { messages: [{ content: 'x'.repeat(300 * 1024) }] }), asinCtx(ASIN))).status).toBe(413)
  })

  it('rejects malformed input: bad JSON 400, bad shape 422, bad id or ASIN 404', async () => {
    session.userId = A
    expect((await reports.POST(post('http://t', '{not json'))).status).toBe(400)
    expect((await reports.POST(post('http://t', { ...copilotReport, asin: 'nope' }))).status).toBe(422)
    expect((await reports.POST(post('http://t', { ...copilotReport, kind: 'other' }))).status).toBe(422)
    expect((await report.GET(req('http://t'), idCtx('not-a-uuid'))).status).toBe(404)
    expect((await convo.GET(req('http://t'), asinCtx('lowercase00'))).status).toBe(404)
  })

  it('keeps only the most recent messages of a long conversation', async () => {
    session.userId = A
    const messages = Array.from({ length: MAX_MESSAGES_PER_CONVERSATION + 20 }, (_, i) => ({ role: 'user', content: `m${i}` }))
    await convo.PUT(put('http://t', { messages }), asinCtx(ASIN))
    const got = (await (await convo.GET(req('http://t'), asinCtx(ASIN))).json()) as { messages: { content: string }[] }
    expect(got.messages).toHaveLength(MAX_MESSAGES_PER_CONVERSATION)
    expect(got.messages.at(-1)?.content).toBe(`m${MAX_MESSAGES_PER_CONVERSATION + 19}`)
  })

  it('recent products: newest activity first, deduped, capped at 5, per user', async () => {
    const at = (minsAgo: number) => new Date(Date.now() - minsAgo * 60_000).toISOString()
    // A: a chat on P1 an hour ago, a report on P2 30 min ago, a report on P1
    // 5 min ago (so P1 is newest and appears once), and six more products.
    await pool().query(`INSERT INTO conversations (user_id, asin, messages, updated_at) VALUES ($1, 'P100000001', '[]', $2)`, [A, at(60)])
    const report = `INSERT INTO saved_reports (user_id, kind, asin, title, payload, created_at) VALUES ($1, 'copilot', $2, 't', '{"schema_version":1,"data":{}}', $3)`
    await pool().query(report, [A, 'P200000002', at(30)])
    await pool().query(report, [A, 'P100000001', at(5)])
    for (let i = 3; i <= 8; i++) await pool().query(report, [A, `P${i}0000000${i}`, at(100 + i)])
    // B has activity too, on a product A never touched.
    await pool().query(report, [B, 'PB00000000', at(1)])

    session.userId = A
    const a = (await (await recent.GET()).json()) as { products: { asin: string }[] }
    expect(a.products.map((p) => p.asin)).toEqual(['P100000001', 'P200000002', 'P300000003', 'P400000004', 'P500000005'])

    session.userId = B
    const b = (await (await recent.GET()).json()) as { products: { asin: string }[] }
    expect(b.products.map((p) => p.asin)).toEqual(['PB00000000'])

    session.userId = null
    expect((await recent.GET()).status).toBe(401)
  })

  it('deleting the user cascades to their reports and conversations', async () => {
    const tmp = 'test-user-cascade'
    await pool().query(`INSERT INTO "user" (id, name, email, "emailVerified") VALUES ($1, 'C', 'c@test.invalid', true)`, [tmp])
    session.userId = tmp
    await reports.POST(post('http://t', copilotReport))
    await convo.PUT(put('http://t', { messages: [{ role: 'user', content: 'hi' }] }), asinCtx(ASIN))
    await pool().query(`DELETE FROM "user" WHERE id = $1`, [tmp])
    const { rows } = await pool().query(
      `SELECT (SELECT count(*) FROM saved_reports WHERE user_id = $1)::int AS r,
              (SELECT count(*) FROM conversations WHERE user_id = $1)::int AS c`,
      [tmp],
    )
    expect(rows[0]).toEqual({ r: 0, c: 0 })
  })
})
