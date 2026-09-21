'use client'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ScoreCard } from '@/components/dashboard/score-card'
import { TopicAnalysis } from '@/components/dashboard/topic-analysis'
import { QualityBreakdown } from '@/components/dashboard/quality-breakdown'
import { SentimentTimeline } from '@/components/dashboard/sentiment-timeline'
import { PhraseClouds } from '@/components/dashboard/phrase-clouds'
import { ReviewDistribution } from '@/components/dashboard/review-distribution'
import { CompetitorMarketPanel } from '@/components/dashboard/competitor-market-panel'
import { DemoModeBanner } from '@/components/dashboard/demo-mode-banner'
import { DashboardLoading, RouteFallback, SkeletonGrid, SkeletonPanel } from '@/components/dashboard/loading'
import { exportToPDF } from '@/lib/exportReport'
import { DEMO_ASIN } from '@/lib/demo-config'
import { isAbortError } from '@/lib/abort'
import { useDashboardExport } from './dashboard-export-context'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function DashboardPageContent() {
  const [mounted, setMounted] = useState(false)
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const searchParams = useSearchParams()
  // `isDemo` drives the onboarding banner — if no ?asin= was specified, the
  // user landed here without analyzing a real product, so we silently load the
  // demo TOZO listing and surface that fact via <DemoModeBanner />.
  const asinParam = searchParams.get('asin')
  const isDemo = !asinParam
  const asin = asinParam || DEMO_ASIN

  const { setAnalysis, setOnExport, setIsExporting } = useDashboardExport()

  useEffect(() => {
    setMounted(true)
    let cancelled = false
    // Switching products must drop the previous product's requests, not just
    // ignore their results. The POST below starts the backend's 3-5 minute
    // pipeline, so an abandoned load would otherwise hold a connection open
    // for minutes — and the browser only allows a handful per origin.
    const controller = new AbortController()

    const loadAnalysis = async () => {
      setLoading(true)
      setData(null)
      // Reset the error too, or a failure is permanent for the rest of the
      // session. Render order is `if (loading)` then `if (error)`, so after one
      // product fails, switching to another fetches fine, stores its data, and
      // still paints the previous product's error box over it. Every sibling
      // page already does this (brief, conversations, reviews, compare); this
      // was the only loader that forgot.
      setError(null)
      try {
        // try sessionStorage first — set by landing page
        const cached = sessionStorage.getItem(`analysis_${asin}`)
        if (cached) {
          if (!cancelled) {
            setData(JSON.parse(cached))
            setLoading(false)
          }
          return
        }

        // fallback — fetch directly from API
        const response = await fetch(`${API_URL}/analyze/${asin}`, { signal: controller.signal })
        if (cancelled) return
        if (!response.ok) {
          // not cached in API yet — run analysis
          const analyzeRes = await fetch(`${API_URL}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url_or_asin: asin }),
            signal: controller.signal,
          })
          if (cancelled) return
          if (!analyzeRes.ok) throw new Error('Analysis failed')
          const result = await analyzeRes.json()
          if (!cancelled) setData(result)
        } else {
          const result = await response.json()
          if (!cancelled) setData(result)
        }
      } catch (err) {
        // A deliberate abort is not a failure — the component is unmounting or
        // already loading a different ASIN, so leave the error state alone.
        if (isAbortError(err)) return
        if (!cancelled) setError('Failed to load analysis. Make sure backend is running.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadAnalysis()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [asin])

  useEffect(() => {
    if (!data) {
      setAnalysis(null)
      setOnExport(null)
      return
    }

    setAnalysis(data)
    setOnExport(async () => {
      setIsExporting(true)
      try {
        await exportToPDF(data)
      } finally {
        setIsExporting(false)
      }
    })
  }, [data, setAnalysis, setOnExport, setIsExporting])

  if (!mounted) return null

  if (loading) return (
    <div className="p-4 md:p-6">
      <DashboardLoading
        note={`Loading analysis for ${asin}`}
        slowNote="First load runs the review pipeline and warms the vector index — later loads are cached."
      >
        {/* Mirrors the real sections below: 4 score cards, the 7/5 split, and
            the full-width sentiment panel. Same grid classes, so nothing
            reflows when the data lands. */}
        <SkeletonGrid count={4} />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <SkeletonPanel className="h-72 lg:col-span-7" />
          <SkeletonPanel className="h-72 lg:col-span-5" />
        </div>
        <SkeletonPanel className="h-56" />
      </DashboardLoading>
    </div>
  )

  if (error) return (
    <div className="p-6">
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
        {error}
      </div>
    </div>
  )

  // extract real values from API response
  const risk      = data?.risk        || {}
  const summary   = data?.summary     || {}
  const features  = data?.features    || {}
  const topics    = summary.top_topics || []

  const overallScore    = Math.round((1 - risk.risk_score) * 100)
  const sentimentAvg    = features.rating_avg || 0
  const pctNegative     = summary.pct_negative || 0
  const pctPositive     = summary.pct_positive || 0
  const totalReviews    = summary.total_reviews || 0
  const sentimentRating = summary.avg_rating || features.rating_avg || 0

  return (
    <div className="p-4 md:p-6 space-y-6">
      {isDemo && <DemoModeBanner productName={data?.product_name} />}

      {/* Section 1 - Score Overview */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <ScoreCard
          title="Overall Listing Score"
          value={overallScore}
          suffix="/100"
          color="blue"
          progress={overallScore}
          subtext={`${pctPositive}% positive reviews`}
          subtextColor="green"
          delay={1}
        />
        <ScoreCard
          title="Return Risk"
          value={risk.risk_pct || 0}
          suffix="%"
          color="amber"
          badge={`${risk.risk_label || 'UNKNOWN'} RISK`}
          subtext={risk.explanation || ''}
          subtextColor={risk.risk_label === 'HIGH' ? 'red' : 'green'}
          delay={2}
        />
        <ScoreCard
          title="Review Sentiment"
          value={parseFloat(sentimentAvg.toFixed(1))}
          suffix="/5.0"
          color="default"
          stars={sentimentAvg}
          subtext={`from ${totalReviews} reviews`}
          delay={3}
        />
        <ScoreCard
          title="Negative Reviews"
          value={pctNegative}
          suffix="%"
          color="red"
          progress={pctNegative}
          subtext={`${pctPositive}% are positive`}
          subtextColor={pctNegative > 40 ? 'red' : 'green'}
          delay={4}
        />
      </div>

      {/* Section 2 - Two Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7">
          <TopicAnalysis
            asin={asin}
            topics={topics}
            features={features}
            summary={summary}
            riskInsight={risk?.explanation}
          />
        </div>
        <div className="lg:col-span-5">
          <QualityBreakdown asin={asin} risk={risk} features={features} />
        </div>
      </div>

      {/* Section 3 - Compound sentiment by star rating */}
      <SentimentTimeline sentimentByRating={summary.sentiment_by_rating} />

      {/* Section 4 - Three Columns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <PhraseClouds type="positive" topics={topics} />
        <PhraseClouds type="negative" topics={topics} />
        <ReviewDistribution
          starDistribution={summary.raw_star_distribution}
        />
      </div>

      {/* Section 5 - Market context. Synthetic competitor data from
          competitor_search; deep-links to /dashboard/compare for the
          side-by-side metrics view. */}
      <CompetitorMarketPanel
        asin={asin}
        maxResults={3}
        showCompareCta
        staggerIndex={8}
      />
    </div>
  )
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <DashboardPageContent />
    </Suspense>
  )
}