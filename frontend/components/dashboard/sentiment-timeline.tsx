'use client'

import { useEffect, useMemo, useState, useRef } from 'react'

const FALLBACK_TIMELINE_DATA = [
  { month: 'Aug 24', overall: 3.8, battery: 3.2, reviews: 28 },
  { month: 'Sep 24', overall: 3.7, battery: 3.0, reviews: 31 },
  { month: 'Oct 24', overall: 3.6, battery: 2.8, reviews: 29 },
  { month: 'Nov 24', overall: 3.5, battery: 2.6, reviews: 35 },
  { month: 'Dec 24', overall: 3.4, battery: 2.4, reviews: 42 },
  { month: 'Jan 25', overall: 3.3, battery: 2.2, reviews: 38 },
  { month: 'Feb 25', overall: 3.2, battery: 1.8, reviews: 34 },
  { month: 'Mar 25', overall: 3.1, battery: 1.6, reviews: 32 },
  { month: 'Apr 25', overall: 3.0, battery: 1.5, reviews: 28 },
  { month: 'May 25', overall: 2.9, battery: 1.4, reviews: 31 },
  { month: 'Jun 25', overall: 2.8, battery: 1.3, reviews: 29 },
  { month: 'Jul 25', overall: 2.7, battery: 1.2, reviews: 26 },
  { month: 'Aug 25', overall: 2.6, battery: 1.1, reviews: 24 },
  { month: 'Sep 25', overall: 2.7, battery: 1.3, reviews: 22 },
  { month: 'Oct 25', overall: 2.8, battery: 1.4, reviews: 25 },
  { month: 'Nov 25', overall: 2.8, battery: 1.5, reviews: 28 },
  { month: 'Dec 25', overall: 2.9, battery: 1.6, reviews: 30 },
  { month: 'Jan 26', overall: 2.8, battery: 1.5, reviews: 27 },
]

/** Map compound score (-1..1) to the chart's 1–5 vertical scale (matches grid labels). */
function compoundToChartY(compound: number): number {
  return 1 + (compound + 1) * 2
}

/** Pandas period keys look like "2024-01" */
function formatPeriodKey(periodKey: string): string {
  const m = periodKey.match(/^(\d{4})-(\d{2})/)
  if (!m) return periodKey
  const y = parseInt(m[1], 10)
  const month = parseInt(m[2], 10) - 1
  const d = new Date(y, month, 1)
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
}

export type SentimentTimelineProps = {
  sentimentTimeline?: Record<string, number> | null
  sentimentByRating?: Record<string, number> | null
}

export function SentimentTimeline({
  sentimentTimeline,
  sentimentByRating: _sentimentByRating,
}: SentimentTimelineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const [animate, setAnimate] = useState(false)
  const chartRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 500)
    return () => clearTimeout(timer)
  }, [])

  const { mode, realPoints } = useMemo(() => {
    const raw = sentimentTimeline && typeof sentimentTimeline === 'object' ? sentimentTimeline : null
    const keys = raw ? Object.keys(raw).sort() : []
    if (!raw || keys.length === 0) {
      return {
        mode: 'fallback' as const,
        realPoints: null as null | { month: string; compound: number; chartY: number }[],
      }
    }
    const points = keys.map((periodKey) => {
      const compound = raw[periodKey]
      return {
        month: formatPeriodKey(periodKey),
        compound,
        chartY: compoundToChartY(compound),
      }
    })
    return { mode: 'real' as const, realPoints: points }
  }, [sentimentTimeline])

  const chartSeries = useMemo(() => {
    if (mode === 'real' && realPoints && realPoints.length > 0) {
      return realPoints.map((p) => ({
        month: p.month,
        overall: p.chartY,
        battery: p.chartY,
        compound: p.compound,
        reviews: 0,
      }))
    }
    return FALLBACK_TIMELINE_DATA.map((d) => ({ ...d, compound: undefined as number | undefined }))
  }, [mode, realPoints])

  const width = 800
  const height = 250
  const padding = { top: 20, right: 40, bottom: 40, left: 40 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  const n = chartSeries.length
  const xStep = n <= 1 ? 0 : chartWidth / (n - 1)
  const xAt = (i: number) => (n <= 1 ? chartWidth / 2 : i * xStep)

  const yScale = (value: number) => chartHeight - ((value - 1) / 4) * chartHeight

  const createPath = (key: 'overall' | 'battery') => {
    return chartSeries.map((d, i) => {
      const x = xAt(i)
      const y = yScale(d[key])
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`
    }).join(' ')
  }

  const firmwareUpdateIndex = 6

  const showDualLines = mode === 'fallback'
  const showFirmware = mode === 'fallback'

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-8">
      <h3 className="font-medium text-text-primary mb-1">Review Sentiment Timeline</h3>
      <p className="text-sm text-text-secondary mb-4">Last 18 months by month</p>

      <div className="relative overflow-x-auto" ref={chartRef}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full min-w-[600px]"
          style={{ maxHeight: '280px' }}
        >
          <g transform={`translate(${padding.left}, ${padding.top})`}>
            {[1, 2, 3, 4, 5].map((val) => (
              <g key={val}>
                <line
                  x1={0}
                  y1={yScale(val)}
                  x2={chartWidth}
                  y2={yScale(val)}
                  stroke="#2A2A3A"
                  strokeDasharray="4 4"
                />
                <text
                  x={-10}
                  y={yScale(val)}
                  fill="#4A4A6A"
                  fontSize={10}
                  textAnchor="end"
                  dominantBaseline="middle"
                  className="font-mono"
                >
                  {val}
                </text>
              </g>
            ))}

            {showFirmware && (
              <>
                <line
                  x1={firmwareUpdateIndex * (chartWidth / (FALLBACK_TIMELINE_DATA.length - 1))}
                  y1={0}
                  x2={firmwareUpdateIndex * (chartWidth / (FALLBACK_TIMELINE_DATA.length - 1))}
                  y2={chartHeight}
                  stroke="#4A4A6A"
                  strokeDasharray="6 4"
                />
                <text
                  x={firmwareUpdateIndex * (chartWidth / (FALLBACK_TIMELINE_DATA.length - 1))}
                  y={-8}
                  fill="#8B8BA7"
                  fontSize={9}
                  textAnchor="middle"
                >
                  Firmware update v2.1
                </text>
              </>
            )}

            {showDualLines && (
              <path
                d={createPath('battery')}
                fill="none"
                stroke="#F59E0B"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`transition-all duration-1000 ${animate ? 'opacity-100' : 'opacity-0'}`}
                style={{
                  strokeDasharray: animate ? 'none' : '1000',
                  strokeDashoffset: animate ? '0' : '1000',
                }}
              />
            )}

            <path
              d={createPath('overall')}
              fill="none"
              stroke="#2DD4BF"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`transition-all duration-1000 ${animate ? 'opacity-100' : 'opacity-0'}`}
              style={{
                strokeDasharray: animate ? 'none' : '1000',
                strokeDashoffset: animate ? '0' : '1000',
              }}
            />

            {chartSeries.map((d, i) => (
              <g key={i}>
                <circle
                  cx={xAt(i)}
                  cy={yScale(d.overall)}
                  r={hoveredIndex === i ? 6 : 4}
                  fill="#2DD4BF"
                  className="cursor-pointer transition-all"
                  onMouseEnter={() => setHoveredIndex(i)}
                  onMouseLeave={() => setHoveredIndex(null)}
                />
                {showDualLines && (
                  <circle
                    cx={xAt(i)}
                    cy={yScale(d.battery)}
                    r={hoveredIndex === i ? 6 : 4}
                    fill="#F59E0B"
                    className="cursor-pointer transition-all"
                    onMouseEnter={() => setHoveredIndex(i)}
                    onMouseLeave={() => setHoveredIndex(null)}
                  />
                )}
              </g>
            ))}

            {chartSeries.map((d, i) =>
              i % 3 === 0 ? (
                <text
                  key={`lbl-${i}`}
                  x={xAt(i)}
                  y={chartHeight + 20}
                  fill="#4A4A6A"
                  fontSize={9}
                  textAnchor="middle"
                  className="font-mono"
                >
                  {d.month}
                </text>
              ) : null,
            )}

            {hoveredIndex !== null && chartSeries[hoveredIndex] && (
              <g
                transform={`translate(${xAt(hoveredIndex)}, ${yScale(chartSeries[hoveredIndex].overall) - 60})`}
              >
                <rect
                  x={-70}
                  y={0}
                  width={140}
                  height={showDualLines ? 50 : 38}
                  fill="#16161F"
                  stroke="#2A2A3A"
                  rx={6}
                />
                <text x={0} y={15} fill="#F1F0F7" fontSize={10} textAnchor="middle" className="font-medium">
                  {chartSeries[hoveredIndex].month}
                </text>
                {mode === 'real' && 'compound' in chartSeries[hoveredIndex] && chartSeries[hoveredIndex].compound !== undefined ? (
                  <text x={0} y={30} fill="#2DD4BF" fontSize={9} textAnchor="middle">
                    Compound: {chartSeries[hoveredIndex].compound!.toFixed(3)}
                  </text>
                ) : (
                  <>
                    <text x={-45} y={30} fill="#2DD4BF" fontSize={9} textAnchor="start">
                      Overall: {chartSeries[hoveredIndex].overall}
                    </text>
                    <text x={-45} y={42} fill="#F59E0B" fontSize={9} textAnchor="start">
                      Battery: {chartSeries[hoveredIndex].battery}
                    </text>
                    <text x={45} y={36} fill="#8B8BA7" fontSize={8} textAnchor="end">
                      {chartSeries[hoveredIndex].reviews} reviews
                    </text>
                  </>
                )}
              </g>
            )}
          </g>
        </svg>
      </div>

      <div className="flex items-center gap-6 mt-4 text-xs flex-wrap">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-accent-teal" />
          <span className="text-text-secondary">
            {mode === 'real' ? 'Avg. compound sentiment' : 'Overall Sentiment'}
          </span>
        </div>
        {showDualLines && (
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-accent-amber" />
            <span className="text-text-secondary">Battery Sentiment</span>
          </div>
        )}
      </div>
    </div>
  )
}
