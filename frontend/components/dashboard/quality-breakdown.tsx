'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { Check, X, AlertTriangle, ArrowRight, Sparkles } from 'lucide-react'

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
  /** Used to build the /assistant deep-link for the "Ask Copilot" CTA. */
  asin?: string
  risk?: RiskInput | null
  features?: FeaturesInput | null
}

type CheckStatus = 'good' | 'critical' | 'warning'

type QualityCheck = { label: string; status: CheckStatus; value: string }

// There is deliberately no placeholder data in this panel.
//
// It used to carry a FALLBACK_CHECKS / FALLBACK_RECOMMENDATIONS pair of invented
// findings — 'Image count (only 3, need 7+)', 'Primary image background: white bg
// missing', and three recommendations naming a headphone and a '20hr claim' — that
// rendered whenever the payload had no usable numeric fields. The backend always
// populates risk + features (_generate_risk_explanation in src/fusion.py can never
// return empty), so they never showed in practice. But /dashboard JSON.parse's its
// sessionStorage cache without validating the shape, so a payload change is all it
// would take to make them live, and two of those six checks are exactly what the
// real image audit will measure.
//
// Same class of problem as the CLIP claims deleted in f69e6d60: an empty state is
// honest about having no data, a fabricated one is not.

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
  if (!text) return []

  const cleaned = text.replace(/^Risk drivers:\s*/i, '').trim()
  const segments = cleaned
    .split(';')
    .map((s) => s.trim())
    .filter(Boolean)

  if (segments.length === 0) return []

  const recs = segments.slice(0, 3).map((s) => {
    const line = s.charAt(0).toUpperCase() + s.slice(1)
    const body = line.endsWith('.') ? line : `${line}.`
    return `Address this driver: ${body}`
  })

  // Not padded to a fixed count. However many drivers the model actually
  // reported is the honest number of recommendations to show.
  return recs
}

export function QualityBreakdown({ asin, risk, features }: QualityBreakdownProps) {
  const { qualityChecks, recommendations } = useMemo(
    () => ({
      qualityChecks: buildQualityChecks(risk, features),
      recommendations: buildRecommendations(risk?.explanation),
    }),
    [risk, features],
  )

  // Phrase the deep-link question using actual risk signals when we have them,
  // so the Copilot lands with concrete context instead of a generic prompt.
  const askCopilotHref = useMemo(() => {
    if (!asin) return null
    const label = risk?.risk_label?.toUpperCase()
    const pct = typeof risk?.risk_pct === 'number' ? Math.round(risk.risk_pct) : null
    const question =
      label && pct != null
        ? `My listing's return risk is ${label} at ${pct}%. Walk me through the highest-priority changes to bring it down — what should I fix first, and why?`
        : `What concrete changes should I prioritize to improve this listing's conversion and reduce returns? Rank them by impact.`
    return `/assistant?asin=${encodeURIComponent(asin)}&mode=copilot&q=${encodeURIComponent(question)}`
  }, [asin, risk?.risk_label, risk?.risk_pct])

  return (
    <div className="space-y-4">
      <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-6">
        <h3 className="font-medium text-text-primary mb-4">Listing Quality Breakdown</h3>

        {qualityChecks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-12 text-center">
            <p className="text-sm text-muted-foreground">No listing signals available yet.</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Run a full analysis to see review sentiment, rating gaps and return risk for this ASIN.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {qualityChecks.map((check, index) => (
              <QualityItem key={`${check.label}-${index}`} {...check} />
            ))}
          </div>
        )}
      </div>

      <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-7">
        <h3 className="font-medium text-text-primary mb-4">AI Recommendations</h3>

        {recommendations.length === 0 ? (
          <p className="text-sm text-text-muted">
            No risk drivers reported for this listing, so there is nothing to recommend from the
            current signals.
          </p>
        ) : (
          <div className="space-y-3">
            {recommendations.map((rec, index) => (
              <div key={index} className="flex items-start gap-2 text-sm text-text-secondary">
                <ArrowRight className="w-4 h-4 text-accent-blue flex-shrink-0 mt-0.5" />
                <span>{rec}</span>
              </div>
            ))}
          </div>
        )}

        {askCopilotHref && (
          <div className="mt-4 pt-4 border-t border-border">
            <Link
              href={askCopilotHref}
              className="group flex items-center justify-between gap-3 rounded-lg border border-border bg-accent-blue/5 hover:bg-accent-blue/10 hover:border-accent-blue/40 px-3 py-2.5 transition-colors"
            >
              <div className="flex items-center gap-2 min-w-0">
                <Sparkles className="w-4 h-4 text-accent-blue flex-shrink-0" />
                <span className="text-sm font-medium text-text-primary truncate">
                  Ask the Copilot to expand on these
                </span>
              </div>
              <span
                aria-hidden
                className="text-accent-blue transition-transform group-hover:translate-x-0.5 flex-shrink-0"
              >
                →
              </span>
            </Link>
          </div>
        )}
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
