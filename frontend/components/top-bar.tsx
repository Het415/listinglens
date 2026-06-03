'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useTheme } from 'next-themes'
import { Logo } from './logo'
import { Download, ChevronRight, Moon, Sun } from 'lucide-react'

import { DEMO_ASIN } from '@/lib/demo-config'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export function TopBar({
  onExport,
  isExporting,
}: {
  onExport?: (() => Promise<void>) | null
  isExporting?: boolean
}) {
  const searchParams = useSearchParams()
  const asin = searchParams.get('asin') || DEMO_ASIN
  const [productName, setProductName] = useState(asin)
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const themeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    setMounted(true)
  }, [])

  // Keep the breadcrumb name in lock-step with the ASIN. The TopBar lives in a
  // persistent layout, so it does NOT remount when only the ?asin= query param
  // changes — that means we must (a) reset the name on every ASIN change so a
  // stale product never lingers, and (b) re-hydrate it from cache or network.
  useEffect(() => {
    let cancelled = false
    setProductName(asin) // reset first — never show the previous product's name

    const cached = sessionStorage.getItem(`analysis_${asin}`)
    if (cached) {
      try {
        const data = JSON.parse(cached)
        if (data?.product_name) setProductName(data.product_name)
        return
      } catch {
        /* corrupt cache — fall through to network */
      }
    }

    // Not in sessionStorage (deep link, or a product analyzed elsewhere):
    // fetch just the name. Cheap — the backend serves this from cache/disk.
    ;(async () => {
      try {
        const res = await fetch(`${API_URL}/analyze/${asin}`)
        if (!res.ok || cancelled) return
        const data = await res.json()
        if (!cancelled && data?.product_name) setProductName(data.product_name)
      } catch {
        /* keep the ASIN as a graceful fallback */
      }
    })()

    return () => {
      cancelled = true
    }
  }, [asin])

  const effectiveTheme = resolvedTheme ?? 'dark'

  const handleThemeToggle = useCallback(() => {
    const el = themeButtonRef.current
    const current = resolvedTheme ?? 'dark'
    if (!el) {
      setTheme(current === 'dark' ? 'light' : 'dark')
      return
    }

    const next = current === 'dark' ? 'light' : 'dark'
    const rect = el.getBoundingClientRect()
    const x = rect.right
    const y = rect.top
    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    )

    const runClipReveal = () => {
      try {
        const animateOptions: KeyframeAnimationOptions & { pseudoElement?: string } = {
          duration: 500,
          easing: 'ease-in-out',
          pseudoElement: '::view-transition-new(root)',
        }
        document.documentElement.animate(
          {
            clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${endRadius}px at ${x}px ${y}px)`],
          },
          animateOptions,
        )
      } catch {
        /* older browsers */
      }
    }

    if (typeof document.startViewTransition === 'function') {
      const transition = document.startViewTransition(() => {
        setTheme(next)
      })
      transition.ready.then(() => {
        runClipReveal()
      })
    } else {
      setTheme(next)
    }
  }, [resolvedTheme, setTheme])

  return (
    <header className="h-[60px] bg-background-secondary border-b border-border flex items-center justify-between px-4 md:px-6">
      <div className="md:hidden">
        <Link href="/">
          <Logo size="small" />
        </Link>
      </div>
      <nav className="hidden md:flex items-center gap-2 text-sm text-text-secondary">
        <span className="flex items-center gap-2">
          <ChevronRight className="w-4 h-4 text-text-muted" />
          <span className="text-text-primary">{productName}</span>
        </span>
      </nav>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={async () => {
            if (!onExport) return
            await onExport()
          }}
          disabled={!onExport || isExporting}
          className="hidden md:flex items-center gap-2 px-4 py-2 text-sm border border-border rounded-lg text-text-secondary hover:border-border-hover hover:text-text-primary transition-colors disabled:opacity-60 disabled:cursor-not-allowed h-9"
        >
          <Download className="w-4 h-4" />
          <span>{isExporting ? 'Exporting...' : 'Export Report'}</span>
        </button>

        <Link
          href={`/assistant?asin=${encodeURIComponent(asin)}`}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-accent-teal text-white font-medium rounded-lg hover:bg-accent-teal/90 transition-colors h-9"
        >
          Ask AI
        </Link>

        <button
          ref={themeButtonRef}
          type="button"
          onClick={handleThemeToggle}
          aria-label={
            // Until mounted, resolvedTheme is unknown — render a stable label on
            // both server and first client paint to avoid a hydration mismatch.
            !mounted
              ? 'Toggle theme'
              : effectiveTheme === 'dark'
                ? 'Switch to light theme'
                : 'Switch to dark theme'
          }
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-background-card text-text-secondary hover:border-border-hover hover:text-text-primary transition-colors"
        >
          {!mounted ? (
            <span className="size-4 rounded bg-border/60 animate-pulse" aria-hidden />
          ) : effectiveTheme === 'dark' ? (
            <Moon className="size-4" strokeWidth={2} aria-hidden />
          ) : (
            <Sun className="size-4" strokeWidth={2} aria-hidden />
          )}
        </button>
      </div>
    </header>
  )
}
