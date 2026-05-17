'use client'
import { useState } from 'react'
import {
  ShieldAlert,
  ArrowRight,
  Copy,
  Check,
} from 'lucide-react'
import type { Recommendation } from './types'
import { decisionStyle, recommendationToText, toolMeta } from './style-helpers'
import { ConfidenceRing } from './ConfidenceRing'

export function RecommendationCard({
  rec,
  onEvidenceClick,
}: {
  rec: Recommendation
  onEvidenceClick?: (tool: string) => void
}) {
  const style = decisionStyle(rec.decision)
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(recommendationToText(rec))
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable — silently ignore
    }
  }

  return (
    <div
      className={`bg-card border border-border rounded-xl p-5 space-y-5 border-l-4 ${style.borderLeftClass} animate-in fade-in slide-in-from-bottom-2 duration-500`}
    >
      <div className="flex items-center gap-4">
        <ConfidenceRing confidence={rec.confidence} decision={rec.decision} />
        <div className="flex-1 min-w-0">
          <div className={`text-2xl font-bold tracking-tight ${style.textClass}`}>
            {style.label}
          </div>
          <div className="text-xs text-muted-foreground">{style.tagline}</div>
        </div>
        <button
          onClick={handleCopy}
          aria-label="Copy recommendation as plain text"
          title="Copy recommendation"
          className="shrink-0 w-8 h-8 rounded-lg border border-border bg-background-secondary hover:border-blue-500/60 hover:text-foreground text-muted-foreground transition flex items-center justify-center"
        >
          {copied ? (
            <Check className="w-4 h-4 text-emerald-400" />
          ) : (
            <Copy className="w-4 h-4" />
          )}
        </button>
      </div>

      <p className="text-sm leading-relaxed text-foreground">{rec.summary}</p>

      {rec.reasoning_steps.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-xs uppercase tracking-wide text-muted-foreground hover:text-foreground transition">
            Reasoning ({rec.reasoning_steps.length} steps)
          </summary>
          <ol className="mt-2 space-y-1.5 list-decimal pl-5 text-sm text-muted-foreground">
            {rec.reasoning_steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </details>
      )}

      {rec.evidence.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
            Evidence ({rec.evidence.length})
          </div>
          <div className="space-y-2">
            {rec.evidence.map((e, i) => {
              const meta = toolMeta(e.tool)
              const Icon = meta.icon
              const relPct = Math.round(e.relevance * 100)
              return (
                <button
                  key={i}
                  onClick={() => onEvidenceClick?.(e.tool)}
                  title={`Click to highlight ${e.tool} in the trace`}
                  className="w-full text-left bg-background-secondary border border-border rounded-lg p-3 hover:border-blue-500/60 transition group"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div
                      className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 ${meta.bgClass}`}
                    >
                      <Icon className={`w-3 h-3 ${meta.colorClass}`} />
                    </div>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                      Evidence {i + 1} / {rec.evidence.length}
                    </span>
                    <code className={`text-[10px] font-mono ${meta.colorClass} ml-auto`}>
                      {e.tool}
                    </code>
                  </div>
                  <p className="text-xs text-foreground leading-snug mb-2">{e.snippet}</p>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1 bg-background rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500/60 transition-all duration-500"
                        style={{ width: `${relPct}%` }}
                        aria-label={`Relevance ${relPct}%`}
                      />
                    </div>
                    <span className="text-[10px] text-muted-foreground tabular-nums w-8 text-right">
                      {relPct}%
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {rec.risks.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground mb-2">
            <ShieldAlert className="w-3 h-3" />
            Risks
          </div>
          <ul className="space-y-1 text-sm text-muted-foreground list-disc pl-5">
            {rec.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {rec.suggested_next_actions.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground mb-2">
            <ArrowRight className="w-3 h-3" />
            Suggested next actions
          </div>
          <ul className="space-y-1 text-sm text-foreground list-disc pl-5">
            {rec.suggested_next_actions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
