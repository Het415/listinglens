import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GET, POST } from '@/app/api/backend/[...path]/route'

const ctx = (path: string) => ({ params: Promise.resolve({ path: path.split('/').filter(Boolean) }) })

describe('/api/backend proxy', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    process.env.BACKEND_URL = 'https://backend.test'
    process.env.BACKEND_SHARED_SECRET = 's3cret'
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('refuses paths outside the allowlist without calling the backend', async () => {
    for (const [method, path] of [
      ['GET', '/docs'],
      ['GET', '/health'],
      ['GET', '/analyze/not-an-asin'],
      ['POST', '/analyze/B08XPWDSWW'],
      ['GET', '/assistant/query'],
    ] as const) {
      const handler = method === 'GET' ? GET : POST
      const res = await handler(new Request(`http://t/api/backend${path}`, { method }), ctx(path))
      expect(res.status, `${method} ${path}`).toBe(404)
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('adds the secret and visitor IP, and drops cookies', async () => {
    fetchMock.mockResolvedValue(new Response('{"ok":true}', { headers: { 'content-type': 'application/json' } }))
    const res = await GET(
      new Request('http://t/api/backend/competitors/B08XPWDSWW?max_results=3', {
        headers: { cookie: 'better-auth.session_token=abc', 'x-vercel-forwarded-for': '203.0.113.9, 10.0.0.1' },
      }),
      ctx('/competitors/B08XPWDSWW'),
    )
    expect(res.status).toBe(200)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://backend.test/competitors/B08XPWDSWW?max_results=3')
    const headers = init.headers as Headers
    expect(headers.get('x-internal-secret')).toBe('s3cret')
    expect(headers.get('x-client-ip')).toBe('203.0.113.9')
    expect(headers.get('cookie')).toBeNull()
  })

  it('streams SSE through unbuffered with the status untouched', async () => {
    const body = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode('event: started\ndata: {}\n\n'))
        c.close()
      },
    })
    fetchMock.mockResolvedValue(new Response(body, { headers: { 'content-type': 'text/event-stream' } }))
    const res = await POST(
      new Request('http://t/api/backend/agent/query/mock', {
        method: 'POST',
        body: JSON.stringify({ asin: 'B08XPWDSWW', query: 'q' }),
        headers: { 'content-type': 'application/json' },
      }),
      ctx('/agent/query/mock'),
    )
    expect(res.status).toBe(200)
    expect(res.headers.get('x-accel-buffering')).toBe('no')
    expect(res.headers.get('cache-control')).toContain('no-transform')
    expect(await res.text()).toContain('event: started')
  })

  it('maps an unreachable backend to 502', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'))
    const res = await GET(new Request('http://t/api/backend/supported-asins'), ctx('/supported-asins'))
    expect(res.status).toBe(502)
  })
})
