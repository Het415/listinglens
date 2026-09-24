'use client'

import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { ScoreCard } from '@/components/dashboard/score-card'
import type { BriefResponse } from '@/lib/exportBrief'

const PRIORITY_STYLE: Record<string, string> = {
  high: 'bg-accent-red/15 text-accent-red',
  medium: 'bg-accent-amber/15 text-accent-amber',
  low: 'bg-accent-teal/15 text-accent-teal',
}

const oneDecimal = (x: number | undefined | null) => Math.round((x ?? 0) * 10) / 10

/** The body of an executive brief. Shared by the live brief page and saved
 *  reports, so a saved brief looks exactly like the one that was saved. */
export function BriefView({ data, footnote }: { data: BriefResponse; footnote?: string }) {
  const m = data.metrics
  const brief = data.brief
  if (!brief || !m) return null

  return (
    <>
      {/* Headline */}
      <section className="rounded-xl border border-border bg-gradient-to-br from-accent-blue/10 to-transparent p-6">
        <h2 className="text-lg font-medium text-foreground">{brief.headline}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{brief.situation}</p>
      </section>

      {/* KPI row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* One decimal and the same colours as the dashboard's cards, so the
            two views of the same product read the same: whole-number rounding
            turned a 0.4% return risk into "0%" and 24.8% negative into "25%". */}
        <ScoreCard title="Return Risk" value={oneDecimal(m.return_risk?.risk_pct)} suffix="%"
          color="amber" badge={m.return_risk?.risk_label} delay={1} />
        <ScoreCard title="Negative Reviews" value={oneDecimal(m.pct_negative)} suffix="%"
          color="red" progress={oneDecimal(m.pct_negative)} delay={2} />
        <ScoreCard title="Avg Rating" value={oneDecimal(m.avg_rating)} suffix="/5.0" stars={m.avg_rating ?? 0}
          color="teal" delay={3} />
        <ScoreCard
          title="Resolution Rate"
          value={Math.round((m.conversations?.resolution_rate ?? 0) * 100)}
          suffix="%"
          color="blue"
          subtext={m.conversations ? undefined : 'No conversation data'}
          delay={4}
        />
      </div>

      {/* Key findings */}
      <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
        <h2 className="mb-4 text-sm font-medium text-foreground">Key Findings</h2>
        <div className="space-y-3">
          {brief.key_findings.map((f, i) => (
            <div key={i} className="flex gap-3">
              <div className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-accent-blue" />
              <div>
                <div className="text-sm font-medium text-foreground">{f.metric}</div>
                <div className="text-sm text-muted-foreground">{f.insight}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Risks */}
        <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-medium text-foreground">
            <AlertTriangle className="h-4 w-4 text-accent-amber" /> Top Risks
          </h2>
          <ul className="space-y-2">
            {brief.top_risks.map((r, i) => (
              <li key={i} className="flex gap-2 text-sm text-muted-foreground">
                <span className="text-accent-amber">•</span> {r}
              </li>
            ))}
          </ul>
        </section>

        {/* Actions */}
        <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-medium text-foreground">
            <CheckCircle2 className="h-4 w-4 text-accent-teal" /> Recommended Actions
          </h2>
          <div className="space-y-3">
            {brief.recommended_actions.map((a, i) => (
              <div key={i} className="rounded-lg border border-border p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-foreground">{a.action}</span>
                  <span className={`rounded px-2 py-0.5 text-xs font-medium ${PRIORITY_STYLE[a.priority] || 'bg-muted text-muted-foreground'}`}>
                    {a.priority}
                  </span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{a.rationale}</div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <p className="text-center text-xs text-muted-foreground">
        Brief confidence: {Math.round((brief.confidence ?? 0) * 100)}%{footnote ? ` · ${footnote}` : ''}
      </p>
    </>
  )
}
