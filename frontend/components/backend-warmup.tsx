'use client'

import { useEffect } from 'react'
import { DEMO_ASIN } from '@/lib/demo-config'

const STORAGE_KEY = 'll:backend-warmed'

/**
 * Fire-and-forget ping to the backend's /warmup endpoint on app mount.
 *
 * Render's free tier spins the API down after ~15min idle; the first real
 * request after spin-up pays ~30s for FAISS + embeddings + LangGraph compile.
 * Firing /warmup the moment the user lands on any page lets that work happen
 * while they're reading the UI, so their first sample-query click is hot.
 *
 * One ping per browser session — guarded by sessionStorage.
 */
export function BackendWarmup() {
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (sessionStorage.getItem(STORAGE_KEY)) return

    const apiUrl = process.env.NEXT_PUBLIC_API_URL
    if (!apiUrl) return

    sessionStorage.setItem(STORAGE_KEY, '1')

    fetch(`${apiUrl}/warmup`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ asin: DEMO_ASIN }),
      keepalive: true,
    }).catch(() => {
      // best-effort; clear the flag so a later mount can retry
      sessionStorage.removeItem(STORAGE_KEY)
    })
  }, [])

  return null
}
