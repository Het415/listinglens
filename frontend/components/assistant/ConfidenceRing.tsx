'use client'
import type { Recommendation } from './types'
import { decisionStyle } from './style-helpers'

export function ConfidenceRing({
  confidence,
  decision,
}: {
  confidence: number
  decision: Recommendation['decision']
}) {
  const { strokeClass, textClass } = decisionStyle(decision)
  const r = 26
  const C = 2 * Math.PI * r
  const clamped = Math.max(0, Math.min(1, confidence))
  const offset = C * (1 - clamped)

  return (
    <div className="relative w-16 h-16 shrink-0">
      <svg viewBox="0 0 64 64" className="w-full h-full -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="5" className="stroke-border" />
        <circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          strokeWidth="5"
          strokeLinecap="round"
          className={`${strokeClass} transition-all duration-700`}
          style={{ strokeDasharray: C, strokeDashoffset: offset }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className={`text-sm font-bold ${textClass}`}>{Math.round(clamped * 100)}%</span>
      </div>
    </div>
  )
}
