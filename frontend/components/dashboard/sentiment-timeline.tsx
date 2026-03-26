'use client'

import { useEffect, useMemo, useState } from 'react'
import { Info } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

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

/** Short explanation tailored by star level (5★ and 1★ match product copy). */
function starPlainEnglish(stars: number): string {
  switch (stars) {
    case 5:
      return 'Customers who leave 5-star reviews sound very satisfied in their text'
    case 4:
      return 'Customers who leave 4-star reviews mostly sound satisfied, with occasional caveats'
    case 3:
      return 'Customers who leave 3-star reviews often sound mixed or lukewarm in their wording'
    case 2:
      return 'Customers who leave 2-star reviews sound disappointed and often frustrated'
    case 1:
      return 'Customers who leave 1-star reviews express strong dissatisfaction'
    default:
      return ''
  }
}

function barInterpretation(score: number): string {
  if (score > 0) return 'Positive gap from neutral'
  if (score < 0) return 'Negative gap from neutral'
  return 'At neutral — aligned with no positive or negative lean'
}

function RowRatingTooltip({
  stars,
  score,
}: {
  stars: number
  score: number | null
}) {
  const title = `${stars}★ Reviews`

  if (score == null) {
    return (
      <div className="max-w-xs space-y-1.5 text-left">
        <p className="font-medium text-foreground">{title}</p>
        <p className="text-xs leading-snug text-muted-foreground">
          No sentiment score is available for this star level yet.
        </p>
      </div>
    )
  }

  return (
    <div className="max-w-xs space-y-2 text-left">
      <p className="font-medium text-foreground">{title}</p>
      <p className="text-xs text-muted-foreground">
        Sentiment Score:{' '}
        <span className="font-mono tabular-nums text-foreground">{formatCompound(score)}</span>
      </p>
      <p className="text-xs leading-snug text-muted-foreground">{starPlainEnglish(stars)}</p>
      <p className="border-t border-border pt-2 text-xs text-muted-foreground">{barInterpretation(score)}</p>
    </div>
  )
}

const COMPOUND_INFO =
  'Compound score measures how positive or negative the language is in reviews at each star rating. A negative score on 2-star reviews means customers are genuinely upset, not just disappointed.'

export function SentimentTimeline({ sentimentByRating }: SentimentTimelineProps) {
  const [barsReady, setBarsReady] = useState(false)

  useEffect(() => {
    const id = requestAnimationFrame(() => setBarsReady(true))
    return () => cancelAnimationFrame(id)
  }, [])

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
    <div className="animate-fade-up stagger-8 rounded-xl border border-border bg-card p-5 text-card-foreground opacity-0">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="font-medium text-foreground">Rating Sentiment Analysis</h3>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="cursor-pointer rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="About compound score"
            >
              <Info className="h-4 w-4" strokeWidth={2} />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-sm p-3 text-xs leading-relaxed text-balance">
            <p className="text-left text-foreground">{COMPOUND_INFO}</p>
          </TooltipContent>
        </Tooltip>
      </div>
      <p className="mb-6 text-sm text-muted-foreground">
        How satisfied customers actually sound at each star rating — gaps reveal listing expectation mismatches
      </p>

      {empty ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-12 text-center">
          <p className="text-sm text-muted-foreground">No sentiment-by-rating data yet.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Run a full analysis to see how wording lines up with each star level.
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          {rows.map((row) => {
            const score = row.score
            const positive = score != null && score > 0
            const negative = score != null && score < 0
            return (
              <Tooltip key={row.stars} delayDuration={200}>
                <TooltipTrigger asChild>
                  <div
                    className={cn(
                      'flex cursor-pointer flex-col gap-2 rounded-lg px-2 py-2 transition-colors sm:flex-row sm:items-center sm:gap-4',
                      'hover:bg-muted/50',
                    )}
                  >
                    <div className="w-full shrink-0 text-sm font-medium tabular-nums text-foreground sm:w-14">
                      {row.stars}★
                    </div>

                    <div className="h-3 min-w-0 flex-1 overflow-hidden rounded-full bg-border/60">
                      {score != null && (
                        <div
                          className={cn(
                            'h-full rounded-full transition-all duration-700 ease-out',
                            positive && 'bg-accent-teal',
                            negative && 'bg-accent-red',
                            score === 0 && 'bg-muted-foreground/50',
                          )}
                          style={{
                            width: barsReady ? `${row.widthPct}%` : '0%',
                          }}
                        />
                      )}
                    </div>

                    <div className="flex shrink-0 flex-col items-end gap-0.5 text-right sm:min-w-[10.5rem]">
                      <span className="text-sm font-semibold tabular-nums text-foreground">
                        {score == null ? '—' : formatCompound(score)}
                      </span>
                      <span className="text-xs leading-tight text-muted-foreground">{row.label}</span>
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top" align="start" className="max-w-[20rem] px-3 py-2.5 text-left">
                  <RowRatingTooltip stars={row.stars} score={score} />
                </TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      )}
    </div>
  )
}
