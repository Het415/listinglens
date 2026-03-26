'use client'

import Link from 'next/link'
import { Suspense, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ArrowLeft, ChevronDown, ChevronRight } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from 'recharts'

import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(
  /\/$/,
  '',
)

type AnalyzeResponse = {
  asin: string
  product_name?: string
  summary?: {
    total_reviews?: number
    pct_positive?: number
    pct_negative?: number
    sentiment_by_rating?: Record<string, number> | Record<number, number>
    top_topics?: Array<{
      id?: number
      label: string
      keywords?: string[]
      count?: number
    }>
    avg_rating?: number
  }
  features?: Record<string, number> | null
  risk?: {
    risk_score?: number
    risk_pct?: number
    risk_label?: string
    explanation?: string
  }
}

type ReviewRow = {
  review_id: number
  rating: number
  sentiment_label: string
  compound_score: number
  topic_id: number
  body: string
}

function normalizeInputToStars(n: number | undefined): 1 | 2 | 3 | 4 | 5 | null {
  if (!n) return null
  if (n >= 1 && n <= 5) return n as 1 | 2 | 3 | 4 | 5
  return null
}

function compoundColor(compound: number): string {
  return compound >= 0 ? '#2DD4BF' : '#EF4444'
}

function formatCompound(compound: number): string {
  const v = Number.isFinite(compound) ? compound : 0
  return v.toFixed(3)
}

function truncate(s: string, max: number) {
  if (!s) return ''
  if (s.length <= max) return s
  return `${s.slice(0, max - 1)}…`
}

function classifyOverallSentiment(avgCompound: number | undefined): string {
  const v = avgCompound ?? 0
  if (v >= 0.15) return 'Positive'
  if (v <= -0.15) return 'Negative'
  return 'Neutral / Mixed'
}

const SENTIMENT_BY_STAR_CHART_CONFIG = {
  compound: { label: 'Avg compound score', color: '#4F8EF7' },
} as const

function SentimentByStarTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ value?: number; payload?: { starLabel: string } }>
}) {
  if (!active || !payload?.length) return null
  const v = typeof payload[0]?.value === 'number' ? payload[0].value : 0
  const starLabel = payload[0]?.payload?.starLabel || 'Star rating'
  return (
    <div className="border-border/50 bg-background grid min-w-[14rem] gap-2 rounded-lg border px-3 py-2.5 shadow-xl">
      <div className="font-medium text-text-primary">{starLabel}</div>
      <div className="text-[11px] leading-snug text-text-muted">
        This bar shows the average sentiment compound score for reviews with this star rating. Teal = positive, red = negative.
      </div>
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-text-secondary">Avg compound</span>
        <span className="text-xs font-mono text-text-primary tabular-nums">{formatCompound(v)}</span>
      </div>
    </div>
  )
}

function sentimentIndicatorEstimate(params: {
  topicCount?: number
  maxCount: number
  pctPositive?: number
  pctNegative?: number
}) {
  const { topicCount, maxCount, pctPositive, pctNegative } = params
  const count = topicCount ?? 0
  const rel = maxCount > 0 ? count / maxCount : 0
  const basePos = pctPositive ?? 50
  const baseNeg = pctNegative ?? 50

  const positive = Math.min(
    100,
    basePos * (0.82 + 0.18 * rel),
  )
  const negative = Math.min(
    100,
    baseNeg * (0.82 + 0.18 * (1 - rel * 0.65)),
  )

  const sum = positive + negative
  if (sum > 100) {
    return { positive: (positive / sum) * 100, negative: (negative / sum) * 100 }
  }
  return { positive, negative }
}

function ReviewsPageInner() {
  const searchParams = useSearchParams()
  const asinFromQuery = searchParams.get('asin') || 'B08XPWDSWW'
  const [mounted, setMounted] = useState(false)
  const [asin, setAsin] = useState('')

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    setAsin(asinFromQuery)
  }, [asinFromQuery])

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reviewsWarning, setReviewsWarning] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null)
  const [reviews, setReviews] = useState<ReviewRow[]>([])

  useEffect(() => {
    if (!mounted) return
    if (!asin) return

    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError(null)
      setReviewsWarning(null)
      try {
        const analyzeRes = await fetch(`${API_URL}/analyze/${asin}`)

        if (!analyzeRes.ok) {
          throw new Error(`Analysis not found for ASIN ${asin}`)
        }

        const analyzeJson = (await analyzeRes.json()) as AnalyzeResponse

        if (cancelled) return
        setAnalysis(analyzeJson)

        // Reviews endpoint may not exist on older deployments.
        try {
          const reviewsRes = await fetch(`${API_URL}/analyze/${asin}/reviews`)
          if (!reviewsRes.ok) {
            setReviews([])
            setReviewsWarning(
              `Per-review endpoint unavailable (${reviewsRes.status}). Showing summary-based analysis only.`,
            )
          } else {
            const reviewsJson = (await reviewsRes.json()) as {
              asin: string
              total_reviews: number
              reviews: ReviewRow[]
            }
            if (cancelled) return
            setReviews(reviewsJson.reviews || [])
          }
        } catch {
          setReviews([])
          setReviewsWarning('Could not load individual reviews. Showing summary-based analysis only.')
        }
      } catch (e) {
        if (cancelled) return
        const message = e instanceof Error ? e.message : 'Failed to load review analysis'
        setError(message)
        setAnalysis(null)
        setReviews([])
      } finally {
        if (cancelled) return
        setLoading(false)
      }
    }

    run()
    return () => {
      cancelled = true
    }
  }, [asin, mounted])

  const summary = analysis?.summary
  const features = analysis?.features
  const risk = analysis?.risk

  const totalReviews = reviews.length || summary?.total_reviews || 0
  const pctPositive = summary?.pct_positive ?? 0
  const pctNegative = summary?.pct_negative ?? 0
  const avgCompound = typeof features?.avg_compound_score === 'number' ? features.avg_compound_score : undefined

  const sentimentByRating = summary?.sentiment_by_rating || {}
  const topics = summary?.top_topics || []

  // -----------------------
  // Section 4 insights
  // -----------------------
  const keyInsights = useMemo(() => {
    if (!analysis || !summary) return []
    const byRating = sentimentByRating || {}

    const entries = [1, 2, 3, 4, 5].map((star) => {
      const v = (byRating as any)[star] ?? (byRating as any)[String(star)] ?? 0
      return { star, compound: Number(v) }
    })

    const best = [...entries].sort((a, b) => b.compound - a.compound)[0]
    const worst = [...entries].sort((a, b) => a.compound - b.compound)[0]

    const topicMost = [...topics].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))[0]

    const alignmentGap = typeof (features as any)?.rating_sentiment_gap === 'number' ? (features as any).rating_sentiment_gap : undefined

    const alignmentText =
      alignmentGap == null
        ? 'We estimate alignment using rating vs sentiment gap.'
        : alignmentGap <= 0.1
          ? `Ratings align well with sentiment (gap ${alignmentGap.toFixed(2)}).`
          : alignmentGap <= 0.2
            ? `Ratings moderately diverge from sentiment (gap ${alignmentGap.toFixed(2)}).`
            : `Ratings diverge from sentiment (gap ${alignmentGap.toFixed(2)}).`

    const riskLabel = (risk?.risk_label || 'UNKNOWN').toUpperCase()
    const riskPct = typeof risk?.risk_pct === 'number' ? risk.risk_pct : undefined

    return [
      `Best star sentiment: ${best.star}-star reviews (${best.compound >= 0 ? '+' : ''}${best.compound.toFixed(3)}).`,
      `Worst star sentiment: ${worst.star}-star reviews (${worst.compound >= 0 ? '+' : ''}${worst.compound.toFixed(3)}).`,
      `Most discussed topic: “${topicMost?.label || 'N/A'}” with ${topicMost?.count ?? 0} reviews.`,
      `Overall sentiment classification: ${classifyOverallSentiment(avgCompound)}.`,
      `Rating vs sentiment alignment: ${alignmentText} Return risk: ${riskLabel}${riskPct != null ? ` (${Math.round(riskPct)}%)` : ''}.`,
    ]
  }, [analysis, summary, sentimentByRating, topics, features, risk, avgCompound])

  // -----------------------
  // Section 2 chart rows
  // -----------------------
  const sentimentRows = useMemo(() => {
    const rows = [1, 2, 3, 4, 5].map((star) => {
      const v = (sentimentByRating as any)[star] ?? (sentimentByRating as any)[String(star)] ?? 0
      return { star, compound: Number(v) }
    })
    const maxAbs = Math.max(...rows.map((r) => Math.abs(r.compound)), 0.0001)
    return { rows, maxAbs }
  }, [sentimentByRating])

  // -----------------------
  // Section 3 topic cards
  // -----------------------
  const maxTopicCount = useMemo(() => Math.max(...topics.map((t) => t.count ?? 0), 0), [topics])
  const [expandedTopicId, setExpandedTopicId] = useState<number | null>(null)

  // -----------------------
  // Section 5 table controls (filter/sort)
  // -----------------------
  const [query, setQuery] = useState('')
  const [starFilter, setStarFilter] = useState<'all' | '1' | '2' | '3' | '4' | '5'>('all')
  const [sentimentFilter, setSentimentFilter] = useState<'all' | 'positive' | 'neutral' | 'negative'>('all')
  const [sortKey, setSortKey] = useState<'review_id' | 'rating' | 'compound_score'>('review_id')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const pageSize = 25

  useEffect(() => {
    setPage(1)
  }, [query, starFilter, sentimentFilter, sortKey, sortDir])

  const filteredSorted = useMemo(() => {
    const q = query.trim().toLowerCase()
    const rows = reviews.filter((r) => {
      if (starFilter !== 'all') {
        const sf = Number(starFilter)
        if (r.rating !== sf) return false
      }

      if (sentimentFilter !== 'all') {
        if ((r.sentiment_label || '').toLowerCase() !== sentimentFilter) return false
      }

      if (q) {
        const body = r.body?.toLowerCase() || ''
        const topicId = String(r.topic_id || '')
        if (!body.includes(q) && !topicId.includes(q)) return false
      }

      return true
    })

    const sign = sortDir === 'asc' ? 1 : -1
    rows.sort((a, b) => {
      if (sortKey === 'review_id') return sign * (a.review_id - b.review_id)
      if (sortKey === 'rating') return sign * (a.rating - b.rating)
      return sign * (a.compound_score - b.compound_score)
    })

    return rows
  }, [reviews, query, starFilter, sentimentFilter, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(filteredSorted.length / pageSize))
  const pageRows = filteredSorted.slice((page - 1) * pageSize, page * pageSize)

  if (!mounted) return null

  return (
    <div className="p-4 md:p-6 space-y-6 bg-[#0A0A0F] min-h-screen">
      <div className="flex items-center gap-4">
        <Link href="/dashboard" className="text-text-secondary hover:text-text-primary">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-medium text-text-primary">Review Analysis</h1>
          <p className="text-sm text-text-secondary mt-1">
            {asin ? `ASIN ${asin}` : 'Select an ASIN to analyze reviews'}
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {reviewsWarning && !error && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 text-amber-200 text-sm">
          {reviewsWarning}
        </div>
      )}

      {loading && !error && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5 animate-pulse">
                <div className="h-4 w-1/2 bg-[#2A2A3A] rounded" />
                <div className="h-8 w-2/3 bg-[#2A2A3A] rounded mt-4" />
              </div>
            ))}
          </div>
          <div className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5 animate-pulse h-28" />
        </div>
      )}

      {!loading && analysis && (
        <>
          {/* SECTION 1 — Sentiment Overview */}
          <section className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5">
            <h2 className="text-sm font-medium text-text-primary mb-4">Sentiment Overview</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <StatCard label="Total Reviews" value={`${totalReviews}`} />
              <StatCard label="Positive %" value={`${pctPositive}%`} color="text-accent-teal" />
              <StatCard label="Negative %" value={`${pctNegative}%`} color="text-accent-red" />
              <StatCard label="Average Compound Score" value={`${avgCompound != null ? avgCompound.toFixed(3) : 'N/A'}`} />
            </div>
          </section>

          {/* SECTION 2 — Sentiment by Star Rating */}
          <section className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5">
            <div className="flex items-center justify-between gap-4 mb-4">
              <h2 className="text-sm font-medium text-text-primary">Sentiment by Star Rating</h2>
              <p className="text-xs text-text-muted">
                Hover for what this represents.
              </p>
            </div>

            <ChartContainer
              id="sentiment-by-star"
              config={SENTIMENT_BY_STAR_CHART_CONFIG}
              className="aspect-[5/2] w-full"
            >
              <BarChart
                data={sentimentRows.rows.map((r) => ({
                  star: String(r.star),
                  starLabel: `${r.star}★`,
                  compound: Math.abs(r.compound),
                  sign: r.compound >= 0 ? 'pos' : 'neg',
                  raw: r.compound,
                }))}
                layout="vertical"
                margin={{ top: 0, right: 24, bottom: 0, left: 16 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <YAxis
                  dataKey="starLabel"
                  type="category"
                  tickLine={false}
                  axisLine={false}
                  width={44}
                />
                <XAxis
                  type="number"
                  domain={[0, sentimentRows.maxAbs]}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => formatCompound(v)}
                />
                <ChartTooltip
                  content={<SentimentByStarTooltip />}
                  formatter={(value, name, item) => {
                    // show the signed value in tooltip
                    const raw = (item as any)?.payload?.raw
                    return [formatCompound(typeof raw === 'number' ? raw : Number(value)), 'Avg compound']
                  }}
                  cursor={{ fill: 'rgba(42,42,58,0.35)' }}
                />
                <Bar dataKey="compound" radius={[6, 6, 6, 6]} isAnimationActive={false}>
                  {sentimentRows.rows.map((r, idx) => (
                    <Cell key={idx} fill={r.compound >= 0 ? '#2DD4BF' : '#EF4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ChartContainer>
          </section>

          {/* SECTION 3 — Topic Deep Dive */}
          <section className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5">
            <h2 className="text-sm font-medium text-text-primary mb-4">Topic Deep Dive</h2>
            <div className="space-y-3">
              {topics.map((t) => {
                const topicId = t.id ?? -1
                const isOpen = expandedTopicId === topicId
                const sentiment = sentimentIndicatorEstimate({
                  topicCount: t.count,
                  maxCount: maxTopicCount,
                  pctPositive,
                  pctNegative,
                })
                return (
                  <div key={`${topicId}-${t.label}`} className="border border-[#2A2A3A] rounded-xl p-4">
                    <button
                      type="button"
                      onClick={() => setExpandedTopicId(isOpen ? null : topicId)}
                      className="w-full text-left flex items-start justify-between gap-4"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-medium text-text-primary">{t.label}</h3>
                          <span className="text-xs px-2 py-0.5 rounded bg-background-card border border-border text-text-secondary">
                            {t.count ?? 0} reviews
                          </span>
                        </div>
                        <div className="mt-3 flex items-center gap-3">
                          <div className="flex-1 h-2 bg-[#2A2A3A] rounded-full overflow-hidden flex">
                            <div
                              style={{ width: `${sentiment.positive}%`, backgroundColor: '#2DD4BF' }}
                              className="h-full"
                            />
                            <div
                              style={{ width: `${sentiment.negative}%`, backgroundColor: '#EF4444' }}
                              className="h-full"
                            />
                          </div>
                        </div>
                      </div>
                      <div className="text-text-muted mt-1">
                        {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                      </div>
                    </button>

                    {isOpen && (
                      <div className="mt-3 space-y-3">
                        <div className="flex flex-wrap gap-2">
                          {(t.keywords || []).map((k, idx) => (
                            <span
                              key={`${k}-${idx}`}
                              className="text-xs px-2 py-1 rounded border border-[#2A2A3A] text-text-secondary bg-[#0A0A0F]"
                            >
                              {k}
                            </span>
                          ))}
                        </div>
                        <div className="text-xs text-text-muted">
                          Sentiment bar estimates positive vs complaint-heavy mention share using overall sentiment totals.
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </section>

          {/* SECTION 4 — Key Insights */}
          <section className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5">
            <h2 className="text-sm font-medium text-text-primary mb-4">Key Insights</h2>
            <ul className="list-disc pl-5 space-y-2 text-sm text-text-secondary">
              {keyInsights.map((ins, idx) => (
                <li key={idx}>{ins}</li>
              ))}
            </ul>
          </section>

          {/* SECTION 5 — All Reviews (filter/sort) */}
          {reviews.length > 0 ? (
            <section className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <h2 className="text-sm font-medium text-text-primary">All Reviews</h2>
                  <p className="text-xs text-text-muted mt-1">
                    {filteredSorted.length} results. Showing page {page} of {totalPages}.
                  </p>
                </div>
                <div className="text-xs text-text-muted">
                  Sorted client-side. Showing up to 250 reviews from cached data.
                </div>
              </div>

            <div className="grid grid-cols-1 lg:grid-cols-6 gap-3 mb-4">
              <div className="lg:col-span-2">
                <label className="text-xs text-text-secondary block mb-1">Search</label>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search body text or topic id..."
                  className="w-full h-10 bg-[#0A0A0F] border border-[#2A2A3A] rounded-lg px-3 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                />
              </div>
              <div>
                <label className="text-xs text-text-secondary block mb-1">Star</label>
                <select
                  value={starFilter}
                  onChange={(e) => setStarFilter(e.target.value as any)}
                  className="w-full h-10 bg-[#0A0A0F] border border-[#2A2A3A] rounded-lg px-3 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                >
                  <option value="all">All</option>
                  <option value="5">5</option>
                  <option value="4">4</option>
                  <option value="3">3</option>
                  <option value="2">2</option>
                  <option value="1">1</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-text-secondary block mb-1">Sentiment</label>
                <select
                  value={sentimentFilter}
                  onChange={(e) => setSentimentFilter(e.target.value as any)}
                  className="w-full h-10 bg-[#0A0A0F] border border-[#2A2A3A] rounded-lg px-3 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                >
                  <option value="all">All</option>
                  <option value="positive">positive</option>
                  <option value="neutral">neutral</option>
                  <option value="negative">negative</option>
                </select>
              </div>
              <div className="lg:col-span-2">
                <label className="text-xs text-text-secondary block mb-1">Sort</label>
                <div className="flex gap-2">
                  <select
                    value={sortKey}
                    onChange={(e) => setSortKey(e.target.value as any)}
                    className="flex-1 h-10 bg-[#0A0A0F] border border-[#2A2A3A] rounded-lg px-3 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                  >
                    <option value="review_id">Review ID</option>
                    <option value="rating">Rating</option>
                    <option value="compound_score">Compound</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
                    className="w-20 h-10 border border-[#2A2A3A] rounded-lg text-sm text-text-secondary hover:text-text-primary transition-colors"
                  >
                    {sortDir.toUpperCase()}
                  </button>
                </div>
              </div>
            </div>

            <div className="overflow-auto rounded-xl border border-[#2A2A3A] bg-[#0A0A0F]">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-[#16161F] text-text-muted">
                    <th className="text-left px-3 py-2 border-b border-[#2A2A3A]">Review</th>
                    <th className="text-left px-3 py-2 border-b border-[#2A2A3A]">Rating</th>
                    <th className="text-left px-3 py-2 border-b border-[#2A2A3A]">Sentiment</th>
                    <th className="text-left px-3 py-2 border-b border-[#2A2A3A]">Compound</th>
                    <th className="text-left px-3 py-2 border-b border-[#2A2A3A]">Topic</th>
                    <th className="text-left px-3 py-2 border-b border-[#2A2A3A]">Body</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((r) => (
                    <tr key={r.review_id} className="hover:bg-[#16161F] transition-colors">
                      <td className="px-3 py-2 border-b border-[#2A2A3A] font-mono text-text-muted">
                        {r.review_id}
                      </td>
                      <td className="px-3 py-2 border-b border-[#2A2A3A] font-mono text-text-primary">
                        {r.rating}★
                      </td>
                      <td className="px-3 py-2 border-b border-[#2A2A3A] text-text-secondary">
                        {(r.sentiment_label || 'neutral').toLowerCase()}
                      </td>
                      <td className="px-3 py-2 border-b border-[#2A2A3A] font-mono text-text-primary">
                        <span style={{ color: compoundColor(r.compound_score) }}>{formatCompound(r.compound_score)}</span>
                      </td>
                      <td className="px-3 py-2 border-b border-[#2A2A3A] font-mono text-text-muted">
                        {r.topic_id}
                      </td>
                      <td className="px-3 py-2 border-b border-[#2A2A3A] text-text-secondary">
                        {truncate(r.body, 140)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between gap-3 mt-4">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="h-9 px-3 rounded-lg border border-[#2A2A3A] text-text-secondary disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Prev
              </button>
              <div className="text-xs text-text-muted">
                Page {page} / {totalPages}
              </div>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="h-9 px-3 rounded-lg border border-[#2A2A3A] text-text-secondary disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
            </section>
          ) : (
            <section className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5">
              <h2 className="text-sm font-medium text-text-primary">All Reviews</h2>
              <p className="text-sm text-text-secondary mt-2">
                Individual review rows aren’t available from the current API deployment. Once the backend endpoint
                <span className="font-mono text-xs text-text-primary">/analyze/&lt;asin&gt;/reviews</span> is deployed,
                this table will populate automatically.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color?: string
}) {
  return (
    <div className="bg-[#0A0A0F] border border-[#2A2A3A] rounded-xl p-4">
      <div className="text-xs text-text-muted">{label}</div>
      <div className={`text-2xl font-medium mt-2 ${color || 'text-text-primary'}`}>{value}</div>
    </div>
  )
}

export default function ReviewsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Loading...</div>}>
      <ReviewsPageInner />
    </Suspense>
  )
}
