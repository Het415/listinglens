'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Sparkles, X } from 'lucide-react'

import { DEMO_PRODUCT_NAME } from '@/lib/demo-config'

const DISMISS_KEY = 'demo_banner_dismissed'

/**
 * Onboarding banner shown at the top of /dashboard and /dashboard/reviews when
 * the user lands without specifying ?asin= — they're seeing the public TOZO
 * demo, and we want that to be explicit instead of silently misleading.
 *
 * Dismissal is per-tab via sessionStorage (matches the chat-history pattern in
 * /assistant) so a returning visitor isn't nagged across days but isn't stuck
 * with a dismissed banner forever either.
 */
export function DemoModeBanner({ productName }: { productName?: string }) {
  // Hydrate dismissal state from sessionStorage on the client. We render
  // nothing until hydration completes to avoid a flash where the banner
  // appears for one frame before being marked dismissed.
  const [dismissed, setDismissed] = useState(false)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    try {
      setDismissed(sessionStorage.getItem(DISMISS_KEY) === '1')
    } catch {
      // sessionStorage may throw in private-mode browsers; default to showing.
    }
    setHydrated(true)
  }, [])

  if (!hydrated || dismissed) return null

  const handleDismiss = () => {
    setDismissed(true)
    try {
      sessionStorage.setItem(DISMISS_KEY, '1')
    } catch {
      // ignore
    }
  }

  const displayName = productName?.trim() || DEMO_PRODUCT_NAME

  return (
    <div
      role="status"
      aria-live="polite"
      className="relative flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4 rounded-xl border border-accent-blue/30 bg-accent-blue/5 px-4 py-3 pr-12 animate-fade-up opacity-0 stagger-1"
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Sparkles className="w-4 h-4 flex-shrink-0 text-accent-blue" />
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug text-text-primary">
            <span className="font-medium">Demo mode</span>
            <span className="text-text-secondary">
              {' '}— showing{' '}
              <span className="font-medium text-text-primary">{displayName}</span> so
              you can explore the platform without analyzing anything yet.
            </span>
          </p>
        </div>
      </div>

      <Link
        href="/"
        className="group inline-flex flex-shrink-0 items-center gap-1.5 self-start rounded-lg bg-accent-blue px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-blue/90 sm:self-auto"
      >
        Analyze your own product
        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
      </Link>

      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss demo mode banner"
        className="absolute right-2 top-2 rounded-md p-1.5 text-text-muted transition-colors hover:bg-background-secondary hover:text-text-primary"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}
