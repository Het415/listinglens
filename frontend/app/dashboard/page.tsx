'use client'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ScoreCard } from '@/components/dashboard/score-card'
import { TopicAnalysis } from '@/components/dashboard/topic-analysis'
import { QualityBreakdown } from '@/components/dashboard/quality-breakdown'
import { SentimentTimeline } from '@/components/dashboard/sentiment-timeline'
import { PhraseClouds } from '@/components/dashboard/phrase-clouds'
import { ReviewDistribution } from '@/components/dashboard/review-distribution'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function DashboardPageContent() {
  const [mounted, setMounted] = useState(false)
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const searchParams = useSearchParams()
  const asin = searchParams.get('asin') || 'B08XPWDSWW'

  useEffect(() => {
    setMounted(true)
    loadAnalysis()
  }, [asin])

  const loadAnalysis = async () => {
    setLoading(true)
    try {
      // try sessionStorage first — set by landing page
      const cached = sessionStorage.getItem(`analysis_${asin}`)
      if (cached) {
        setData(JSON.parse(cached))
        setLoading(false)
        return
      }

      // fallback — fetch directly from API
      const response = await fetch(`${API_URL}/analyze/${asin}`)
      if (!response.ok) {
        // not cached in API yet — run analysis
        const analyzeRes = await fetch(`${API_URL}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url_or_asin: asin }),
        })
        if (!analyzeRes.ok) throw new Error('Analysis failed')
        const result = await analyzeRes.json()
        setData(result)
      } else {
        const result = await response.json()
        setData(result)
      }
    } catch (err) {
      setError('Failed to load analysis. Make sure backend is running.')
    } finally {
      setLoading(false)
    }
  }

  if (!mounted) return null

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center space-y-3">
        <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto"/>
        <p className="text-muted-foreground text-sm">Loading analysis for {asin}...</p>
      </div>
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
          color="teal"
          progress={100 - pctNegative}
          subtext={`${pctPositive}% are positive`}
          subtextColor={pctNegative > 40 ? 'red' : 'green'}
          delay={4}
        />
      </div>

      {/* Section 2 - Two Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7">
          <TopicAnalysis
            topics={topics}
            features={features}
            summary={summary}
            riskInsight={risk?.explanation}
          />
        </div>
        <div className="lg:col-span-5">
          <QualityBreakdown risk={risk} features={features} />
        </div>
      </div>

      {/* Section 3 - Sentiment Timeline */}
      <SentimentTimeline sentimentByRating={summary.sentiment_by_rating} />

      {/* Section 4 - Three Columns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <PhraseClouds type="positive" topics={topics} />
        <PhraseClouds type="negative" topics={topics} />
        <ReviewDistribution sentimentByRating={summary.sentiment_by_rating} />
      </div>
    </div>
  )
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Loading...</div>}>
      <DashboardPageContent />
    </Suspense>
  )
}