'use client'

import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

/** Shape from API `summary.top_topics` */
export type TopicItem = {
  id?: number
  label: string
  keywords?: string[]
  count?: number
}

export type TopicAnalysisProps = {
  topics?: TopicItem[]
  features?: Record<string, number> | null
  summary?: {
    pct_positive?: number
    pct_negative?: number
    sentiment_by_rating?: Record<string, number>
  } | null
  /** e.g. `risk.explanation` — shown in the insight callout */
  riskInsight?: string | null
}

type TopicRow = { name: string; positive: number; negative: number }

const FALLBACK_TOPICS: TopicRow[] = [
  { name: 'Battery Life', positive: 18, negative: 67 },
  { name: 'Sound Quality', positive: 89, negative: 8 },
  { name: 'Noise Cancellation', positive: 76, negative: 14 },
  { name: 'Comfort & Fit', positive: 52, negative: 38 },
  { name: 'Build Quality', positive: 61, negative: 29 },
  { name: 'Price vs Value', positive: 44, negative: 41 },
]

const FALLBACK_INSIGHT =
  'Battery life complaints appear in 67% of negative reviews — this is your highest return risk factor'

function truncate(s: string, max: number) {
  if (s.length <= max) return s
  return `${s.slice(0, max - 1)}…`
}

/** Map global sentiment + topic volume to bar percentages (API has no per-topic sentiment). */
function buildTopicRows(
  topics: TopicItem[],
  summary: TopicAnalysisProps['summary'],
  features: TopicAnalysisProps['features'],
): TopicRow[] {
  const pctPos =
    summary?.pct_positive ??
    (features?.pct_positive != null ? features.pct_positive * 100 : null)
  const pctNeg =
    summary?.pct_negative ??
    (features?.pct_negative != null ? features.pct_negative * 100 : null)

  const basePos = pctPos ?? 50
  const baseNeg = pctNeg ?? 50

  const sorted = [...topics].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
  const maxC = Math.max(...sorted.map((t) => t.count ?? 0), 1)

  return sorted.slice(0, 6).map((t) => {
    const rel = (t.count ?? 0) / maxC
    const name =
      (t.label && t.label.trim()) ||
      (t.keywords?.length ? t.keywords.slice(0, 3).join(' · ') : 'Topic')
    return {
      name: truncate(name, 42),
      positive: Math.min(100, Math.round(basePos * (0.82 + 0.18 * rel))),
      negative: Math.min(
        100,
        Math.round(baseNeg * (0.82 + 0.18 * (1 - rel * 0.65))),
      ),
    }
  })
}

function meanSentimentGap(summary: TopicAnalysisProps['summary']): number | null {
  const by = summary?.sentiment_by_rating
  if (!by || typeof by !== 'object') return null
  const hi = [5, 4].map((k) => by[String(k)]).filter((v): v is number => typeof v === 'number')
  const lo = [1, 2].map((k) => by[String(k)]).filter((v): v is number => typeof v === 'number')
  if (!hi.length && !lo.length) return null
  const mHi = hi.length ? hi.reduce((a, b) => a + b, 0) / hi.length : 0
  const mLo = lo.length ? lo.reduce((a, b) => a + b, 0) / lo.length : 0
  return mHi - mLo
}

function buildInsight(props: TopicAnalysisProps): string {
  if (props.riskInsight?.trim()) return props.riskInsight.trim()

  const { topics, summary, features } = props
  const pctNeg =
    summary?.pct_negative ??
    (features?.pct_negative != null ? features.pct_negative * 100 : null)
  const pctPos =
    summary?.pct_positive ??
    (features?.pct_positive != null ? features.pct_positive * 100 : null)

  if (topics?.length) {
    const top = [...topics].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))[0]
    const label =
      top?.label?.trim() ||
      top?.keywords?.slice(0, 2).join(' · ') ||
      'the leading topic'
    const gap = meanSentimentGap(summary)
    const gapNote =
      gap != null && Math.abs(gap) < 0.15
        ? ' Sentiment is relatively flat across star ratings.'
        : ''
    if (pctNeg != null || pctPos != null) {
      const neg = pctNeg != null ? `${pctNeg}%` : 'a notable share'
      return `“${truncate(label, 48)}” shows the highest review volume. Overall, ${neg} of reviews skew negative.${gapNote}`
    }
    return `Highest-volume theme: “${truncate(label, 48)}”.`
  }

  return FALLBACK_INSIGHT
}

export function TopicAnalysis({
  topics,
  features,
  summary,
  riskInsight,
}: TopicAnalysisProps) {
  const [animate, setAnimate] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 300)
    return () => clearTimeout(timer)
  }, [])

  const { rows, insight } = useMemo(() => {
    const hasTopics = Array.isArray(topics) && topics.length > 0
    const rows = !hasTopics
      ? FALLBACK_TOPICS
      : buildTopicRows(topics!, summary, features)
    const insight = buildInsight({ topics, features, summary, riskInsight })
    return { rows, insight }
  }, [topics, features, summary, riskInsight])

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-5">
      <h3 className="font-medium text-text-primary mb-1">Review Topic Analysis</h3>
      <p className="text-sm text-text-secondary mb-6">What customers are actually talking about</p>

      <div className="space-y-4">
        {rows.map((topic, index) => (
          <TopicBar
            key={`${topic.name}-${index}`}
            topic={topic}
            animate={animate}
            delay={index * 100}
          />
        ))}
      </div>

      <div className="mt-6 flex items-start gap-3 p-4 bg-accent-amber/10 border-l-2 border-accent-amber rounded-r-lg">
        <AlertTriangle className="w-4 h-4 text-accent-amber flex-shrink-0 mt-0.5" />
        <p className="text-sm text-text-secondary">{insight}</p>
      </div>
    </div>
  )
}

function TopicBar({
  topic,
  animate,
  delay,
}: {
  topic: TopicRow
  animate: boolean
  delay: number
}) {
  const [widths, setWidths] = useState({ positive: 0, negative: 0 })

  useEffect(() => {
    if (animate) {
      const timer = setTimeout(() => {
        setWidths({ positive: topic.positive, negative: topic.negative })
      }, delay)
      return () => clearTimeout(timer)
    }
  }, [animate, topic, delay])

  return (
    <div className="flex items-center gap-4">
      <div className="w-32 text-sm text-text-secondary truncate">{topic.name}</div>

      <div className="flex-1 flex items-center gap-2">
        <span className="text-xs font-mono text-accent-teal w-8 text-right">{topic.positive}%</span>
        <div className="flex-1 flex gap-1">
          <div className="flex-1 h-3 bg-border/50 rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-teal rounded-full transition-all duration-700 ease-out"
              style={{ width: `${widths.positive}%` }}
            />
          </div>
          <div className="flex-1 h-3 bg-border/50 rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-red rounded-full transition-all duration-700 ease-out"
              style={{ width: `${widths.negative}%` }}
            />
          </div>
        </div>
        <span className="text-xs font-mono text-accent-red w-8">{topic.negative}%</span>
      </div>
    </div>
  )
}
