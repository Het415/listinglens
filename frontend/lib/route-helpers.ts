import { NextResponse } from 'next/server'
import { MAX_BODY_BYTES } from './saved'

export function json(body: unknown, status = 200): Response {
  return NextResponse.json(body, { status })
}

export const unauthorized = () => json({ error: 'sign in required' }, 401)
export const notFound = () => json({ error: 'not found' }, 404)

/** Reads a JSON body with a hard size cap. Measured on the actual bytes, not
 *  Content-Length, which a client can leave out or understate. */
export async function readJson(
  request: Request,
): Promise<{ ok: true; value: unknown } | { ok: false; response: Response }> {
  const raw = await request.text()
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return { ok: false, response: json({ error: 'payload too large' }, 413) }
  }
  try {
    return { ok: true, value: JSON.parse(raw) }
  } catch {
    return { ok: false, response: json({ error: 'invalid JSON' }, 400) }
  }
}
