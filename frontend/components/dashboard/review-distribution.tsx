'use client'

import { useEffect, useMemo, useState } from 'react'

/** Compound score per star rating (e.g. from API `summary.sentiment_by_rating`). Keys may be `"1"`–`"5"` or numbers. */
export type SentimentByRating = Record<string, number> | Record<number, number>

const REVIEWS_PER_STAR = 50

const FALLBACK_DISTRIBUTION = [
  { stars: 5, count: 55, color: '#2DD4BF' },
  { stars: 4, count: 44, color: '#5EEAD4' },
  { stars: 3, count: 28, color: '#F59E0B' },
  { stars: 2, count: 31, color: '#FB923C' },
  { stars: 1, count: 89, color: '#EF4444' },
]

export type ReviewDistributionProps = {
  sentimentByRating?: SentimentByRating | null
}

type BarItem = { stars: number; count: number; color: string }

function parseHex(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace('#', '')
  const n = parseInt(h.slice(0, 6), 16)
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
}

function mixHex(a: string, b: string, t: number): string {
  const A = parseHex(a)
  const B = parseHex(b)
  const u = Math.max(0, Math.min(1, t))
  const r = Math.round(A.r + (B.r - A.r) * u)
  const g = Math.round(A.g + (B.g - A.g) * u)
  const bl = Math.round(A.b + (B.b - A.b) * u)
  return `#${[r, g, bl]
    .map((x) => x.toString(16).padStart(2, '0'))
    .join('')}`
}

/** Map compound [-1, 1] to a color from red → amber → teal. */
function sentimentToColor(sentiment: number): string {
  const t = Math.max(-1, Math.min(1, sentiment))
  if (t <= 0) return mixHex('#EF4444', '#F59E0B', t + 1)
  return mixHex('#F59E0B', '#2DD4BF', t)
}

function getSentiment(
  map: SentimentByRating,
  stars: number,
): number | undefined {
  const n = map[stars as keyof typeof map]
  if (typeof n === 'number' && !Number.isNaN(n)) return n
  const s = map[String(stars) as keyof typeof map]
  if (typeof s === 'number' && !Number.isNaN(s)) return s
  return undefined
}

function buildFromSentiment(sentimentByRating: SentimentByRating): BarItem[] {
  const starsOrder = [5, 4, 3, 2, 1] as const
  return starsOrder.map((stars) => {
    const sentiment = getSentiment(sentimentByRating, stars) ?? 0
    return {
      stars,
      count: REVIEWS_PER_STAR,
      color: sentimentToColor(sentiment),
    }
  })
}

function isEmptySentiment(map: SentimentByRating | null | undefined): boolean {
  if (map == null || typeof map !== 'object') return true
  return Object.keys(map).length === 0
}

export function ReviewDistribution({ sentimentByRating }: ReviewDistributionProps) {
  const [animate, setAnimate] = useState(false)

  const distribution = useMemo(() => {
    if (isEmptySentiment(sentimentByRating)) return FALLBACK_DISTRIBUTION
    return buildFromSentiment(sentimentByRating as SentimentByRating)
  }, [sentimentByRating])

  const maxCount = Math.max(...distribution.map((d) => d.count))

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 600)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-8">
      <h3 className="font-medium text-text-primary mb-4">Review Distribution</h3>

      <div className="flex items-end justify-between gap-2 h-36">
        {distribution.map((item, index) => {
          const height = (item.count / maxCount) * 100

          return (
            <div key={item.stars} className="flex flex-col items-center gap-2 flex-1">
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
          )
        })}
      </div>
    </div>
  )
}
