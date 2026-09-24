'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

export type SupportedAsin = { asin: string; name: string }

// One request per page load, shared by every caller: the top bar's product
// switcher lives in a persistent layout and the landing and compare pages ask
// for the same list. A failed request is forgotten so the next mount retries.
let cached: Promise<SupportedAsin[]> | null = null

function load(): Promise<SupportedAsin[]> {
  if (!cached) {
    cached = fetch(apiUrl('/supported-asins'))
      .then(async (res) => {
        if (!res.ok) throw new Error(`supported-asins ${res.status}`)
        const json = (await res.json()) as { asins?: SupportedAsin[] }
        return Array.isArray(json.asins) ? json.asins : []
      })
      .catch(() => {
        cached = null
        return []
      })
  }
  return cached
}

/** The products the backend can analyze. Empty while loading or on failure. */
export function useSupportedAsins(): { products: SupportedAsin[]; loading: boolean } {
  const [products, setProducts] = useState<SupportedAsin[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    load().then((list) => {
      if (cancelled) return
      setProducts(list)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return { products, loading }
}
