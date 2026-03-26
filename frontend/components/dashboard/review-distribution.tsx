'use client'

import { useEffect, useMemo, useState } from 'react'
import { Info } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/** Balanced ingest fallback: same review count per star bucket. */
const REVIEWS_PER_STAR = 50

export type ReviewDistributionProps = {
  /** Real raw star distribution (from API `summary.raw_star_distribution`). */
  starDistribution?: Record<string, number> | Record<number, number> | null
}

type BarItem = {
  stars: number
  count: number
  color: string
}

function getRatingCount(map: ReviewDistributionProps['starDistribution'], stars: number): number | undefined {
  if (map == null || typeof map !== 'object') return undefined
  const n = map[stars as keyof typeof map]
  if (typeof n === 'number' && !Number.isNaN(n)) return n

  const s = map[String(stars) as keyof typeof map]
  if (typeof s === 'number' && !Number.isNaN(s)) return s

  return undefined
}

function starColor(stars: number): string {
  // Requested fixed palette:
  // 5-star teal, 4-star light teal, 3-star neutral gray, 2-star light red, 1-star red.
  if (stars === 5) return '#2DD4BF'
  if (stars === 4) return '#5EEAD4'
  if (stars === 3) return '#6B7280' // neutral gray
  if (stars === 2) return '#FB7185' // light red
  return '#EF4444'
}

export function ReviewDistribution({
  starDistribution,
}: ReviewDistributionProps) {
  const [animate, setAnimate] = useState(false)

  const distribution = useMemo<BarItem[]>(() => {
    const starsOrder = [5, 4, 3, 2, 1] as const
    return starsOrder.map((stars) => {
      const count = getRatingCount(starDistribution, stars) ?? REVIEWS_PER_STAR
      return {
        stars,
        count,
        color: starColor(stars),
      }
    })
  }, [starDistribution])

  const maxCount = Math.max(...distribution.map((d) => d.count))

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 600)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-8">
      <div className="flex items-center justify-between gap-3 mb-4">
        <h3 className="font-medium text-text-primary">Review Distribution</h3>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="cursor-help text-text-muted">
              <Info className="w-4 h-4" />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            Bar height represents the number of reviews per star rating (raw distribution). Falls back to an even 50-per-star preview if unavailable.
          </TooltipContent>
        </Tooltip>
      </div>

      <div className="flex items-end justify-between gap-2 h-36">
        {distribution.map((item, index) => {
          const height = maxCount > 0 ? (item.count / maxCount) * 100 : 0

          return (
            <Tooltip key={item.stars}>
              <TooltipTrigger asChild>
                <div className="flex flex-col items-center gap-2 flex-1 cursor-help">
                  <span className="text-xs font-mono text-text-muted">{item.count}</span>
                  <div className="w-full h-28 flex items-end justify-center">
                    <div
                      className="w-8 rounded-t-lg transition-all duration-700 ease-out"
                      style={{
                        backgroundColor: item.color,
                        height: animate ? `${height}%` : '0%',
                        transitionDelay: `${index * 80}ms`,
                      }}
                    />
                  </div>
                  <div className="flex items-center gap-0.5">
                    <span className="text-xs text-text-secondary">{item.stars}</span>
                    <svg className="w-3 h-3 text-accent-amber fill-current" viewBox="0 0 20 20">
                      <path d="M10 15l-5.878 3.09 1.123-6.545L.489 6.91l6.572-.955L10 0l2.939 5.955 6.572.955-4.756 4.635 1.123 6.545z" />
                    </svg>
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <div className="grid gap-1">
                  <div className="font-medium text-text-primary">{item.stars} star rating</div>
                  <div className="text-xs text-text-secondary">
                    Reviews:{' '}
                    <span className="font-mono text-text-primary">{item.count}</span>
                  </div>
                </div>
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
    </div>
  )
}
