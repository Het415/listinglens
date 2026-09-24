// The one place that decides where backend calls go (audit T-31: eleven files
// used to build this URL by hand, each with its own localhost fallback).
//
// Two modes, switched by NEXT_PUBLIC_API_MODE:
//   - direct (default): the browser calls FastAPI at NEXT_PUBLIC_API_URL.
//   - proxy: the browser calls our own /api/backend/* route, which adds the
//     shared secret server-side. Only switch this on once the backend knows
//     the secret — see docs/INTERNAL_AUTH.md for the order.
//
// Resolution happens per call, never at import: CI builds without the URL set,
// and a throw at module scope would fail every prerender.

const MODE = process.env.NEXT_PUBLIC_API_MODE === 'proxy' ? 'proxy' : 'direct'
const DIRECT_BASE = (process.env.NEXT_PUBLIC_API_URL || '').replace(/\/$/, '')

export function apiBase(): string {
  if (MODE === 'proxy') return '/api/backend'
  if (DIRECT_BASE) return DIRECT_BASE
  // A production build with no URL would silently call the visitor's own
  // localhost. Fail loudly instead; the caller's catch shows the error.
  if (process.env.NODE_ENV === 'production') {
    throw new Error('NEXT_PUBLIC_API_URL is not set for this deployment')
  }
  return 'http://localhost:8000'
}

/** `path` starts with a slash, e.g. `/analyze/B08XPWDSWW`. */
export function apiUrl(path: string): string {
  return `${apiBase()}${path}`
}

/** True when a backend is configured at all. The warmup ping uses this to stay
 *  silent rather than throw in an environment with no backend. */
export function apiConfigured(): boolean {
  return MODE === 'proxy' || Boolean(DIRECT_BASE)
}
