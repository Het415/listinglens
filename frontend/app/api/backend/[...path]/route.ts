// Same-origin proxy to the FastAPI backend. It adds the shared secret
// server-side, so the secret never reaches the browser, and once the backend
// enforces it (docs/INTERNAL_AUTH.md) nothing but this route can spend the
// LLM budget.
//
// Used only when NEXT_PUBLIC_API_MODE=proxy (see lib/api.ts). No session is
// required: anonymous analysis stays open and rate-limited per visitor by the
// backend. Sessions gate data, in /api/me/*.

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
// The worst healthy-provider-failure agent run is ~3.9 min (llm_config's stage
// deadlines). 300 s is also the Hobby-plan ceiling, and it includes streaming.
export const maxDuration = 300

const ASIN = '[A-Z0-9]{10}'

// Exactly the backend routes the browser uses. Anything else is a 404 here,
// so the proxy can't be used to reach /docs, /health internals, or routes
// added to the backend later without a deliberate change.
const ALLOWED: Record<'GET' | 'POST', RegExp[]> = {
  GET: [
    /^\/supported-asins$/,
    new RegExp(`^/analyze/${ASIN}$`),
    new RegExp(`^/analyze/${ASIN}/reviews$`),
    new RegExp(`^/conversations/${ASIN}$`),
    new RegExp(`^/brief/${ASIN}$`),
    new RegExp(`^/competitors/${ASIN}$`),
  ],
  POST: [
    /^\/analyze$/,
    /^\/chat$/,
    /^\/intent\/classify$/,
    /^\/agent\/query$/,
    /^\/agent\/query\/mock$/,
    /^\/assistant\/query$/,
    /^\/warmup$/,
  ],
}

// Request headers worth passing upstream. Cookies in particular are NOT
// forwarded: the backend has no use for the auth session.
const FORWARD_REQUEST_HEADERS = ['content-type', 'accept']
// Response headers worth passing back. Hop-by-hop and encoding headers are
// dropped because fetch has already decoded the body.
const FORWARD_RESPONSE_HEADERS = ['content-type', 'cache-control', 'retry-after', 'x-accel-buffering']

function visitorIp(request: Request): string | null {
  // Vercel overwrites x-forwarded-for with the client IP (anti-spoofing);
  // x-vercel-forwarded-for is the same value but can't be clobbered by a
  // proxy in front of Vercel. Locally none are set and the backend falls back
  // to the TCP peer.
  const raw =
    request.headers.get('x-vercel-forwarded-for') ??
    request.headers.get('x-real-ip') ??
    request.headers.get('x-forwarded-for')
  return raw?.split(',')[0]?.trim() || null
}

async function proxy(request: Request, method: 'GET' | 'POST', segments: string[]): Promise<Response> {
  const path = '/' + segments.map(encodeURIComponent).join('/')
  if (!ALLOWED[method].some((re) => re.test(path))) {
    return Response.json({ error: 'not found' }, { status: 404 })
  }

  const base = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || '').replace(/\/$/, '')
  if (!base) return Response.json({ error: 'backend not configured' }, { status: 500 })

  const headers = new Headers()
  for (const name of FORWARD_REQUEST_HEADERS) {
    const v = request.headers.get(name)
    if (v) headers.set(name, v)
  }
  const secret = process.env.BACKEND_SHARED_SECRET
  if (secret) headers.set('x-internal-secret', secret)
  const ip = visitorIp(request)
  if (ip) headers.set('x-client-ip', ip)

  const search = new URL(request.url).search
  let upstream: Response
  try {
    upstream = await fetch(`${base}${path}${search}`, {
      method,
      headers,
      body: method === 'POST' ? await request.arrayBuffer() : undefined,
      // A browser that navigates away aborts this request; passing the signal
      // on lets the backend notice the disconnect and stop the agent run.
      signal: request.signal,
      cache: 'no-store',
    })
  } catch {
    // Same shape the frontend already treats as a network failure.
    return Response.json({ error: 'backend unreachable' }, { status: 502 })
  }

  const out = new Headers()
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.headers.get(name)
    if (v) out.set(name, v)
  }
  if (out.get('content-type')?.includes('text/event-stream')) {
    // Stream frames through as they arrive — never buffer an SSE body.
    out.set('cache-control', 'no-cache, no-transform')
    out.set('x-accel-buffering', 'no')
  }
  // Status passes through untouched: rate-limit refusals already arrive as a
  // 200 with an SSE `error` frame, and the UI relies on that.
  return new Response(upstream.body, { status: upstream.status, headers: out })
}

type Ctx = { params: Promise<{ path: string[] }> }

export async function GET(request: Request, { params }: Ctx) {
  return proxy(request, 'GET', (await params).path)
}

export async function POST(request: Request, { params }: Ctx) {
  return proxy(request, 'POST', (await params).path)
}
