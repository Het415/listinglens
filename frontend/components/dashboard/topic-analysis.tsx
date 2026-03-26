'use client'

import { useMemo } from 'react'
import { AlertTriangle, Info } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/** Shape from API `summary.top_topics` (keyword categories + rating mix) */
export type TopicItem = {
  id?: number
  label: string
  keywords?: string[]
  count?: number
  pct_negative?: number
  pct_positive?: number
  complaint_level?: 'HIGH' | 'MEDIUM' | 'LOW'
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

type TopicRow = {
  name: string
  positive: number
  negative: number
  count?: number
  keywords?: string[]
  complaint_level?: 'HIGH' | 'MEDIUM' | 'LOW'
  /** True when values come from per-category API (not legacy heuristic) */
  usesRealRatings?: boolean
}

const FALLBACK_TOPICS: TopicRow[] = [
  { name: 'Battery Life', positive: 18, negative: 67, complaint_level: 'HIGH', usesRealRatings: false },
  { name: 'Sound Quality', positive: 89, negative: 8, complaint_level: 'LOW', usesRealRatings: false },
  { name: 'Noise Cancellation', positive: 76, negative: 14, complaint_level: 'LOW', usesRealRatings: false },
  { name: 'Comfort & Fit', positive: 52, negative: 38, complaint_level: 'MEDIUM', usesRealRatings: false },
  { name: 'Build Quality', positive: 61, negative: 29, complaint_level: 'MEDIUM', usesRealRatings: false },
  { name: 'Price vs Value', positive: 44, negative: 41, complaint_level: 'MEDIUM', usesRealRatings: false },
]

const FALLBACK_INSIGHT =
  'Battery life complaints appear in 67% of negative reviews — this is your highest return risk factor'

function truncate(s: string, max: number) {
  if (s.length <= max) return s
  return `${s.slice(0, max - 1)}…`
}

function hasRealTopicRatings(t: TopicItem): boolean {
  return (
    typeof t.pct_negative === 'number' &&
    !Number.isNaN(t.pct_negative) &&
    typeof t.pct_positive === 'number' &&
    !Number.isNaN(t.pct_positive)
  )
}

function clampPct(n: number): number {
  return Math.min(100, Math.max(0, n))
}

function formatTopicPct(n: number): string {
  const x = Math.round(n * 10) / 10
  return Number.isInteger(x) ? `${x}%` : `${x.toFixed(1)}%`
}

/** Which side of the mention mix is larger — one number per row for scanability. */
function dominantSignal(negative: number, positive: number): 'negative' | 'positive' {
  if (negative > positive) return 'negative'
  if (positive > negative) return 'positive'
  return 'negative'
}

function complaintDotClass(level: 'HIGH' | 'MEDIUM' | 'LOW'): string {
  switch (level) {
    case 'HIGH':
      return 'bg-accent-red shadow-[0_0_0_2px_rgba(239,68,68,0.25)]'
    case 'MEDIUM':
      return 'bg-accent-amber shadow-[0_0_0_2px_rgba(245,158,11,0.25)]'
    case 'LOW':
      return 'bg-accent-green shadow-[0_0_0_2px_rgba(34,197,94,0.22)]'
    default:
      return 'bg-border'
  }
}

/**
 * Prefer real per-category % (4–5★ vs 1–2★ among reviews that mention the category).
 * Rows are sorted by pct_negative descending (worst first). Falls back to a heuristic for older payloads.
 */
function buildTopicRows(
  topics: TopicItem[],
  summary: TopicAnalysisProps['summary'],
  features: TopicAnalysisProps['features'],
): TopicRow[] {
  const useReal = topics.length > 0 && topics.every(hasRealTopicRatings)

  if (useReal) {
    const ordered = [...topics]
      .sort((a, b) => (b.pct_negative ?? 0) - (a.pct_negative ?? 0))
      .slice(0, 6)

    return ordered.map((t) => {
      const rawName =
        (t.label && t.label.trim()) ||
        (t.keywords?.length ? t.keywords.slice(0, 3).join(' · ') : 'Topic')
      return {
        name: rawName,
        positive: clampPct(t.pct_positive!),
        negative: clampPct(t.pct_negative!),
        count: t.count,
        keywords: t.keywords,
        complaint_level: t.complaint_level,
        usesRealRatings: true,
      }
    })
  }

  const sortedByCount = [...topics].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
  const slice = sortedByCount.slice(0, 6)

  const pctPos =
    summary?.pct_positive ??
    (features?.pct_positive != null ? features.pct_positive * 100 : null)
  const pctNeg =
    summary?.pct_negative ??
    (features?.pct_negative != null ? features.pct_negative * 100 : null)

  const basePos = pctPos ?? 50
  const baseNeg = pctNeg ?? 50
  const maxC = Math.max(...sortedByCount.map((x) => x.count ?? 0), 1)

  const rows = slice.map((t) => {
    const rel = (t.count ?? 0) / maxC
    const rawName =
      (t.label && t.label.trim()) ||
      (t.keywords?.length ? t.keywords.slice(0, 3).join(' · ') : 'Topic')
    return {
      name: rawName,
      positive: Math.min(100, Math.round(basePos * (0.82 + 0.18 * rel))),
      negative: Math.min(100, Math.round(baseNeg * (0.82 + 0.18 * (1 - rel * 0.65)))),
      count: t.count,
      keywords: t.keywords,
      usesRealRatings: false,
    }
  })

  return rows.sort((a, b) => b.negative - a.negative)
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
    const sorted = [...topics].sort((a, b) => (b.pct_negative ?? 0) - (a.pct_negative ?? 0))
    const top = sorted[0]
    const label =
      top?.label?.trim() ||
      top?.keywords?.slice(0, 2).join(' · ') ||
      'the leading topic'
    const gap = meanSentimentGap(summary)
    const gapNote =
      gap != null && Math.abs(gap) < 0.15
        ? ' Sentiment is relatively flat across star ratings.'
        : ''

    if (top && hasRealTopicRatings(top)) {
      const negShare = formatTopicPct(top.pct_negative!)
      const posShare = formatTopicPct(top.pct_positive!)
      const level = top.complaint_level
      const risk =
        level === 'HIGH'
          ? ' Complaint-heavy ratings on this theme are elevated — worth prioritizing in listings and support.'
          : level === 'MEDIUM'
            ? ' Watch this theme in returns and Q&A.'
            : ''
      return `“${label}” has the highest share of low-star mentions among categories shown (${negShare} from 1–2★ reviews vs ${posShare} from 4–5★).${risk}${gapNote}`
    }

    if (pctNeg != null || pctPos != null) {
      const neg = pctNeg != null ? `${pctNeg}%` : 'a notable share'
      return `“${truncate(label, 52)}” shows the highest review volume. Overall, ${neg} of reviews skew negative.${gapNote}`
    }
    return `Highest-volume theme: “${truncate(label, 52)}”.`
  }

  return FALLBACK_INSIGHT
}

export function TopicAnalysis({
  topics,
  features,
  summary,
  riskInsight,
}: TopicAnalysisProps) {
  const { rows, insight } = useMemo(() => {
    const hasTopics = Array.isArray(topics) && topics.length > 0
    const rows = !hasTopics
      ? [...FALLBACK_TOPICS].sort((a, b) => b.negative - a.negative)
      : buildTopicRows(topics!, summary, features)
    const insight = buildInsight({ topics, features, summary, riskInsight })
    return { rows, insight }
  }, [topics, features, summary, riskInsight])

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-5">
      <div className="flex items-center justify-between gap-3 mb-1">
        <h3 className="font-medium text-text-primary">Review Topic Analysis</h3>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="cursor-help text-text-muted">
              <Info className="w-4 h-4" />
            </div>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            Categories come from keywords in your reviews. Each row shows the stronger signal: either the share of mentions
            from 1–2★ reviews (Negative) or from 4–5★ reviews (Positive). 3★ reviews are not counted. Rows are sorted with the
            highest complaint share first.
          </TooltipContent>
        </Tooltip>
      </div>
      <p className="text-sm text-text-secondary mb-5">
        Where low-star reviews concentrate — sorted by complaint share (highest first)
      </p>

      <div className="divide-y divide-border">
        {rows.map((topic, index) => (
          <TopicRowBlock key={`${topic.name}-${index}`} topic={topic} />
        ))}
      </div>

      <div className="mt-6 flex items-start gap-3 p-4 bg-accent-amber/10 border-l-2 border-accent-amber rounded-r-lg">
        <AlertTriangle className="w-4 h-4 text-accent-amber flex-shrink-0 mt-0.5" />
        <p className="text-sm text-text-secondary">{insight}</p>
      </div>
    </div>
  )
}

function TopicRowBlock({ topic }: { topic: TopicRow }) {
  const negLabel = formatTopicPct(topic.negative)
  const posLabel = formatTopicPct(topic.positive)
  const dominant = dominantSignal(topic.negative, topic.positive)
  const showNegative = dominant === 'negative'

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-base font-medium leading-snug text-text-primary [overflow-wrap:anywhere]">
              {topic.name}
            </span>
            {topic.complaint_level ? (
              <>
                <span
                  className={cn('inline-block size-2 shrink-0 rounded-full', complaintDotClass(topic.complaint_level))}
                  aria-hidden
                />
                <span
                  className={cn(
                    'text-xs font-semibold uppercase tracking-wide',
                    topic.complaint_level === 'HIGH' && 'text-accent-red',
                    topic.complaint_level === 'MEDIUM' && 'text-accent-amber',
                    topic.complaint_level === 'LOW' && 'text-accent-green',
                  )}
                >
                  {topic.complaint_level}
                </span>
              </>
            ) : null}
          </div>

          <div className="flex shrink-0 items-baseline sm:justify-end">
            {showNegative ? (
              <span className="tabular-nums text-sm">
                <span className="font-semibold text-accent-red">{negLabel}</span>{' '}
                <span className="font-medium text-accent-red/90">Negative</span>
              </span>
            ) : (
              <span className="tabular-nums text-sm">
                <span className="font-semibold text-accent-teal">{posLabel}</span>{' '}
                <span className="font-medium text-accent-teal/90">Positive</span>
              </span>
            )}
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <div className="grid gap-1.5">
          <div className="font-medium text-text-primary">{topic.name}</div>
          {topic.complaint_level ? (
            <div className="text-xs text-text-secondary">
              Complaint level: <span className="font-semibold text-text-primary">{topic.complaint_level}</span> (from 1–2★
              share among mentions)
            </div>
          ) : null}
          <div className="text-xs text-text-secondary">
            Row highlights the <span className="font-medium text-text-primary">stronger</span> signal:{' '}
            {showNegative ? (
              <>
                <span className="text-accent-red">{negLabel}</span> from 1–2★ (vs{' '}
                <span className="text-accent-teal">{posLabel}</span> from 4–5★).
              </>
            ) : (
              <>
                <span className="text-accent-teal">{posLabel}</span> from 4–5★ (vs{' '}
                <span className="text-accent-red">{negLabel}</span> from 1–2★).
              </>
            )}
          </div>
          {typeof topic.count === 'number' && !Number.isNaN(topic.count) && (
            <div className="text-xs text-text-secondary">
              Reviews mentioning this category:{' '}
              <span className="font-mono text-text-primary">{topic.count}</span>
            </div>
          )}
          {topic.keywords?.length ? (
            <div className="text-xs text-text-secondary">
              Sample keywords:{' '}
              <span className="font-medium text-text-primary">{topic.keywords.slice(0, 4).join(' · ')}</span>
            </div>
          ) : null}
          {topic.usesRealRatings ? null : (
            <div className="text-xs text-text-muted border-t border-border pt-1.5">
              Estimated shares — run a fresh analysis for per-category star mix.
            </div>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  )
}
