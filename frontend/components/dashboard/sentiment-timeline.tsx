'use client'

import { useMemo } from 'react'

import { cn } from '@/lib/utils'

const STAR_ORDER = [5, 4, 3, 2, 1] as const

export type SentimentTimelineProps = {
  sentimentByRating?: Record<string, number> | Record<number, number> | null
}

function getScore(map: SentimentTimelineProps['sentimentByRating'], stars: number): number | null {
  if (!map || typeof map !== 'object') return null
  const n = map[stars as unknown as keyof typeof map]
  if (typeof n === 'number' && !Number.isNaN(n)) return n
  const s = map[String(stars) as keyof typeof map]
  if (typeof s === 'number' && !Number.isNaN(s)) return s
  return null
}

function hasAnyScores(map: SentimentTimelineProps['sentimentByRating']): boolean {
  if (!map || typeof map !== 'object') return false
  return STAR_ORDER.some((s) => getScore(map, s) != null)
}

/** Plain-English label from compound score (-1…1). */
function compoundLabel(score: number): string {
  if (score > 0.3) return 'Very Positive'
  if (score >= 0.1 && score <= 0.3) return 'Positive'
  if (score >= -0.1 && score <= 0.1) return 'Mixed'
  if (score >= -0.3 && score < -0.1) return 'Negative'
  return 'Very Negative'
}

function formatCompound(score: number): string {
  const rounded = Math.round(score * 1000) / 1000
  return rounded.toFixed(3)
}

export function SentimentTimeline({ sentimentByRating }: SentimentTimelineProps) {
  const rows = useMemo(() => {
    if (!hasAnyScores(sentimentByRating)) return null
    return STAR_ORDER.map((stars) => {
      const score = getScore(sentimentByRating, stars)
      return {
        stars,
        score,
        widthPct: score == null ? 0 : Math.min(100, Math.abs(score) * 100),
        label: score == null ? '—' : compoundLabel(score),
      }
    })
  }, [sentimentByRating])

  const empty = rows == null

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-8">
      <h3 className="font-medium text-text-primary mb-1">Rating Sentiment Analysis</h3>
      <p className="text-sm text-text-secondary mb-6">
        How satisfied customers actually sound at each star rating — gaps reveal listing expectation mismatches
      </p>

      {empty ? (
        <div className="rounded-lg border border-dashed border-border bg-background/50 py-12 px-4 text-center">
          <p className="text-sm text-text-secondary">No sentiment-by-rating data yet.</p>
          <p className="text-xs text-text-muted mt-1">Run a full analysis to see how wording lines up with each star level.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {rows.map((row) => {
            const score = row.score
            const positive = score != null && score > 0
            const negative = score != null && score < 0
            return (
              <div
                key={row.stars}
                className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4"
              >
                <div className="w-full shrink-0 text-sm font-medium tabular-nums text-text-primary sm:w-14">
                  {row.stars}★
                </div>

                <div className="h-3 min-w-0 flex-1 overflow-hidden rounded-full bg-border/60">
                  {score != null && (
                    <div
                      className={cn(
                        'h-full rounded-full transition-[width] duration-700 ease-out',
                        positive && 'bg-accent-teal',
                        negative && 'bg-accent-red',
                        score === 0 && 'bg-text-muted/50',
                      )}
                      style={{ width: `${row.widthPct}%` }}
                    />
                  )}
                </div>

                <div className="flex shrink-0 flex-col items-end gap-0.5 text-right sm:min-w-[10.5rem]">
                  <span className="tabular-nums text-sm font-semibold text-text-primary">
                    {score == null ? '—' : formatCompound(score)}
                  </span>
                  <span className="text-xs leading-tight text-text-muted">{row.label}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
