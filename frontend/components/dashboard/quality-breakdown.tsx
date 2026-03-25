'use client'

import { useMemo } from 'react'
import { Check, X, AlertTriangle, ArrowRight } from 'lucide-react'

export type RiskInput = {
  risk_label?: string
  risk_pct?: number
  explanation?: string
}

export type FeaturesInput = {
  pct_negative?: number
  rating_avg?: number
  rating_sentiment_gap?: number
  pct_positive?: number
}

export type QualityBreakdownProps = {
  risk?: RiskInput | null
  features?: FeaturesInput | null
}

type CheckStatus = 'good' | 'critical' | 'warning'

type QualityCheck = { label: string; status: CheckStatus; value: string }

const FALLBACK_CHECKS: QualityCheck[] = [
  { label: 'Title keyword coverage', status: 'good', value: '84%' },
  { label: 'Image count (only 3, need 7+)', status: 'critical', value: '43%' },
  { label: 'Primary image background', status: 'critical', value: 'white bg missing' },
  { label: 'Description length', status: 'warning', value: '67%' },
  { label: 'Bullet points structure', status: 'good', value: '91%' },
  { label: 'A+ Content present', status: 'warning', value: 'not detected' },
]

const FALLBACK_RECOMMENDATIONS = [
  'Add 4 more product images showing the headphone from different angles and in-use scenarios',
  'Revise product description to address battery expectations — set realistic 20hr claim prominently',
  'Respond to top 10 battery complaints publicly to show customer service quality',
]

/** pct_negative is 0–1 (API `features`). */
function negativeShareStatus(pct: number): CheckStatus {
  if (pct > 0.35) return 'critical'
  if (pct > 0.25) return 'warning'
  return 'good'
}

function ratingStatus(avg: number): CheckStatus {
  if (avg < 3.0) return 'critical'
  if (avg < 4.0) return 'warning'
  return 'good'
}

function gapStatus(gap: number): CheckStatus {
  if (gap > 0.2) return 'critical'
  if (gap > 0.1) return 'warning'
  return 'good'
}

function modelRiskStatus(label?: string): CheckStatus {
  const u = (label || '').toUpperCase()
  if (u === 'HIGH') return 'critical'
  if (u === 'MEDIUM') return 'warning'
  return 'good'
}

function positiveShareStatus(pct: number): CheckStatus {
  if (pct < 0.35) return 'critical'
  if (pct < 0.45) return 'warning'
  return 'good'
}

function buildQualityChecks(risk: RiskInput | null | undefined, features: FeaturesInput | null | undefined): QualityCheck[] {
  const checks: QualityCheck[] = []

  const pn = features?.pct_negative
  if (typeof pn === 'number' && !Number.isNaN(pn)) {
    checks.push({
      label: 'Negative review sentiment share',
      status: negativeShareStatus(pn),
      value: `${(pn * 100).toFixed(0)}%`,
    })
  }

  const ra = features?.rating_avg
  if (typeof ra === 'number' && !Number.isNaN(ra)) {
    checks.push({
      label: 'Average customer rating',
      status: ratingStatus(ra),
      value: `${ra.toFixed(1)} / 5`,
    })
  }

  const gap = features?.rating_sentiment_gap
  if (typeof gap === 'number' && !Number.isNaN(gap)) {
    checks.push({
      label: 'Rating vs. review sentiment gap',
      status: gapStatus(gap),
      value: gap.toFixed(2),
    })
  }

  const pp = features?.pct_positive
  if (typeof pp === 'number' && !Number.isNaN(pp)) {
    checks.push({
      label: 'Positive review sentiment share',
      status: positiveShareStatus(pp),
      value: `${(pp * 100).toFixed(0)}%`,
    })
  }

  const rp = risk?.risk_pct
  const rl = risk?.risk_label
  if (typeof rp === 'number' && !Number.isNaN(rp)) {
    checks.push({
      label: 'Return / refund risk (model)',
      status: modelRiskStatus(rl),
      value: `${rp}%`,
    })
  }

  return checks
}

function buildRecommendations(explanation?: string): string[] {
  const text = explanation?.trim()
  if (!text) return [...FALLBACK_RECOMMENDATIONS]

  const cleaned = text.replace(/^Risk drivers:\s*/i, '').trim()
  const segments = cleaned
    .split(';')
    .map((s) => s.trim())
    .filter(Boolean)

  if (segments.length === 0) return [...FALLBACK_RECOMMENDATIONS]

  const recs = segments.slice(0, 3).map((s) => {
    const line = s.charAt(0).toUpperCase() + s.slice(1)
    const body = line.endsWith('.') ? line : `${line}.`
    return `Address this driver: ${body}`
  })

  while (recs.length < 3) {
    recs.push(
      'Monitor review sentiment and adjust listing copy so ratings and review tone stay aligned.',
    )
  }

  return recs.slice(0, 3)
}

function shouldUseFallback(
  risk: RiskInput | null | undefined,
  features: FeaturesInput | null | undefined,
): boolean {
  if (risk == null && features == null) return true
  const checks = buildQualityChecks(risk, features)
  return checks.length === 0
}

export function QualityBreakdown({ risk, features }: QualityBreakdownProps) {
  const { qualityChecks, recommendations } = useMemo(() => {
    if (shouldUseFallback(risk, features)) {
      return {
        qualityChecks: FALLBACK_CHECKS,
        recommendations: [...FALLBACK_RECOMMENDATIONS],
      }
    }
    return {
      qualityChecks: buildQualityChecks(risk, features),
      recommendations: buildRecommendations(risk?.explanation),
    }
  }, [risk, features])

  return (
    <div className="space-y-4">
      <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-6">
        <h3 className="font-medium text-text-primary mb-4">Listing Quality Breakdown</h3>

        <div className="space-y-3">
          {qualityChecks.map((check, index) => (
            <QualityItem key={`${check.label}-${index}`} {...check} />
          ))}
        </div>
      </div>

      <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-7">
        <h3 className="font-medium text-text-primary mb-4">AI Recommendations</h3>

        <div className="space-y-3">
          {recommendations.map((rec, index) => (
            <div key={index} className="flex items-start gap-2 text-sm text-text-secondary">
              <ArrowRight className="w-4 h-4 text-accent-blue flex-shrink-0 mt-0.5" />
              <span>{rec}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function QualityItem({
  label,
  status,
  value,
}: {
  label: string
  status: CheckStatus
  value: string
}) {
  const statusConfig = {
    good: {
      icon: Check,
      iconColor: 'text-accent-green',
      badgeColor: 'bg-accent-green/20 text-accent-green',
      badgeText: 'GOOD',
    },
    critical: {
      icon: X,
      iconColor: 'text-accent-red',
      badgeColor: 'bg-accent-red/20 text-accent-red',
      badgeText: 'CRITICAL',
    },
    warning: {
      icon: AlertTriangle,
      iconColor: 'text-accent-amber',
      badgeColor: 'bg-accent-amber/20 text-accent-amber',
      badgeText: 'WARNING',
    },
  }

  const config = statusConfig[status]
  const Icon = config.icon

  return (
    <div className="flex items-center gap-3 text-sm">
      <Icon className={`w-4 h-4 ${config.iconColor} flex-shrink-0`} />
      <span className="text-text-secondary flex-1">{label}</span>
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${config.badgeColor}`}>
        {config.badgeText}
      </span>
      <span className="font-mono text-xs text-text-muted w-24 text-right">{value}</span>
    </div>
  )
}
