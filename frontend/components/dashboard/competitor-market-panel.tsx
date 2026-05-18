'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Info, Star, ThumbsDown, ThumbsUp } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')

type Competitor = {
  asin: string
  title: string
  brand: string
  price_usd: number
  rating: number
  review_count: number
  top_features: string[]
  top_complaints: string[]
}

type CompetitorSearchResponse = {
  asin: string
  category: string
  n_results: number
  competitors: Competitor[]
}

export type CompetitorMarketPanelProps = {
  /** ASIN of the seller's product. Drives the GET /competitors/{asin} call. */
  asin: string
  /** Cap on competitors fetched. Backend default is 5; pass 3 for the dashboard summary. */
  maxResults?: number
  /**
   * When true, render a "See in Compare" CTA in the header that deep-links to
   * `/dashboard/compare?asin={asin}`. Set to false on the Compare page itself.
   */
  showCompareCta?: boolean
  /**
   * Optional stagger index (matches the dashboard's animate-fade-up rhythm).
   * Pass 6+ when mounting below the existing dashboard sections.
   */
  staggerIndex?: number
}

/**
 * Market-context panel that surfaces the `competitor_search` MCP tool's
 * output as read-only competitor cards. The data is intentionally synthetic
 * (see backend/data/mock_market_data.json) — the cards are explicitly labeled
 * so a seller never confuses these with their own analyzed catalog data.
 *
 * Used on `/dashboard` (with CTA → /dashboard/compare?asin=…) and on
 * `/dashboard/compare` (CTA hidden, since the user is already there).
 */
export function CompetitorMarketPanel({
  asin,
  maxResults = 5,
  showCompareCta = false,
  staggerIndex,
}: CompetitorMarketPanelProps) {
  const [data, setData] = useState<CompetitorSearchResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`${API_URL}/competitors/${asin}?max_results=${maxResults}`)
        if (!res.ok) {
          // 404 = ASIN outside the supported catalog (e.g. user just typed in
          // a random ASIN). Surface a quiet empty-state, not a red error.
          if (res.status === 404) {
            if (!cancelled) {
              setData(null)
              setError('no_competitors')
            }
            return
          }
          throw new Error(`HTTP ${res.status}`)
        }
        const json = (await res.json()) as CompetitorSearchResponse
        if (!cancelled) setData(json)
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'fetch_failed')
          setData(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [asin, maxResults])

  const staggerClass = useMemo(() => {
    // Stagger classes are defined in globals.css for 1…8. Outside that range
    // we skip the delay rather than emit an unknown class.
    if (typeof staggerIndex !== 'number') return ''
    if (staggerIndex < 1 || staggerIndex > 8) return ''
    return `stagger-${staggerIndex}`
  }, [staggerIndex])

  const compareHref = `/dashboard/compare?asin=${encodeURIComponent(asin)}`

  // Skeleton while loading — matches the dashboard's pulse cards.
  if (loading) {
    return (
      <section
        aria-label="Market competitors"
        className={`bg-background-card border border-border rounded-xl p-5 ${staggerClass}`}
      >
        <PanelHeader showCompareCta={showCompareCta} compareHref={compareHref} />
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="bg-background border border-border rounded-lg p-4 space-y-3 animate-pulse"
            >
              <div className="h-4 w-3/4 bg-muted rounded" />
              <div className="h-3 w-1/2 bg-muted rounded" />
              <div className="h-3 w-full bg-muted rounded" />
              <div className="h-3 w-5/6 bg-muted rounded" />
            </div>
          ))}
        </div>
      </section>
    )
  }

  // Quiet empty-state for ASINs outside the supported catalog (404) or any
  // fetch failure. The dashboard already shows the user's own data above this
  // section, so a noisy error toast would be disproportionate.
  if (error || !data || data.competitors.length === 0) {
    return (
      <section
        aria-label="Market competitors"
        className={`bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 ${staggerClass}`}
      >
        <PanelHeader showCompareCta={false} compareHref={compareHref} />
        <p className="text-sm text-text-muted mt-3">
          No market reference data available for this ASIN yet.
        </p>
      </section>
    )
  }

  return (
    <section
      aria-label="Market competitors"
      className={`bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 ${staggerClass}`}
    >
      <PanelHeader
        showCompareCta={showCompareCta}
        compareHref={compareHref}
        category={data.category}
        count={data.competitors.length}
      />

      <p className="text-sm text-text-secondary mt-1">
        How comparable products in the{' '}
        <span className="font-medium text-text-primary">
          {formatCategory(data.category)}
        </span>{' '}
        category position themselves on price, rating, and customer pain points.
      </p>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {data.competitors.map((c) => (
          <CompetitorCard key={c.asin} competitor={c} />
        ))}
      </div>
    </section>
  )
}

function PanelHeader({
  showCompareCta,
  compareHref,
  category,
  count,
}: {
  showCompareCta: boolean
  compareHref: string
  category?: string
  count?: number
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <h3 className="font-medium text-text-primary">Market Competitors</h3>
        <SyntheticBadge />
        {typeof count === 'number' && count > 0 ? (
          <span className="text-xs text-text-muted">
            {count} {count === 1 ? 'product' : 'products'}
            {category ? ` · ${formatCategory(category)}` : ''}
          </span>
        ) : null}
      </div>

      {showCompareCta ? (
        <Link
          href={compareHref}
          className="inline-flex items-center gap-1.5 self-start rounded-lg border border-accent-blue/40 bg-accent-blue/10 px-3 py-1.5 text-xs font-medium text-accent-blue transition-colors hover:bg-accent-blue/20 sm:self-auto group"
        >
          Open in Compare
          <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
        </Link>
      ) : null}
    </div>
  )
}

function SyntheticBadge() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-help items-center gap-1 rounded-md border border-accent-amber/40 bg-accent-amber/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-amber">
          <Info className="w-3 h-3" />
          Synthetic
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <div className="text-xs">
          These competitor cards are seeded mock data — plausible but not
          scraped from Amazon. They illustrate the market shape so the seller
          can position against it, but they are not in the analyzed catalog,
          so the per-ASIN Compare metrics (return risk, sentiment) aren&apos;t
          available for them.
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

function CompetitorCard({ competitor }: { competitor: Competitor }) {
  const {
    asin,
    title,
    brand,
    price_usd,
    rating,
    review_count,
    top_features,
    top_complaints,
  } = competitor

  return (
    <article className="flex h-full flex-col gap-3 rounded-lg border border-border bg-background p-4 transition-colors hover:border-border/70">
      <header className="flex flex-col gap-1">
        <h4 className="text-sm font-medium leading-snug text-text-primary [overflow-wrap:anywhere]">
          {title}
        </h4>
        <div className="flex items-center gap-2 text-xs text-text-secondary">
          <span className="font-medium text-text-primary">{brand}</span>
          <span aria-hidden>·</span>
          <span className="font-mono text-text-muted">{asin}</span>
        </div>
      </header>

      <div className="flex items-center justify-between text-sm">
        <span className="font-semibold tabular-nums text-text-primary">
          ${price_usd.toFixed(2)}
        </span>
        <span className="flex items-center gap-1.5 text-text-secondary">
          <Star className="w-3.5 h-3.5 fill-accent-amber text-accent-amber" />
          <span className="tabular-nums font-medium text-text-primary">
            {rating.toFixed(1)}
          </span>
          <span className="text-xs text-text-muted">
            ({formatReviewCount(review_count)})
          </span>
        </span>
      </div>

      {top_features.length > 0 ? (
        <ChipRow
          icon={<ThumbsUp className="w-3 h-3 text-accent-green" />}
          label="Strengths"
          items={top_features}
          variant="positive"
        />
      ) : null}

      {top_complaints.length > 0 ? (
        <ChipRow
          icon={<ThumbsDown className="w-3 h-3 text-accent-red" />}
          label="Complaints"
          items={top_complaints}
          variant="negative"
        />
      ) : null}
    </article>
  )
}

function ChipRow({
  icon,
  label,
  items,
  variant,
}: {
  icon: React.ReactNode
  label: string
  items: string[]
  variant: 'positive' | 'negative'
}) {
  const chipClass =
    variant === 'positive'
      ? 'border-accent-green/30 bg-accent-green/10 text-accent-green'
      : 'border-accent-red/30 bg-accent-red/10 text-accent-red'

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">
        {icon}
        {label}
      </div>
      <div className="flex flex-wrap gap-1">
        {items.map((item, i) => (
          <span
            key={`${label}-${i}`}
            className={`inline-block rounded-md border px-1.5 py-0.5 text-[11px] leading-snug ${chipClass}`}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function formatCategory(slug: string): string {
  return slug
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function formatReviewCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`
  return String(n)
}
