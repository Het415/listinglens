import {
  MessageSquareText,
  AlertTriangle,
  GitCompare,
  LineChart,
  TrendingUp,
  Wrench,
} from 'lucide-react'
import type { Recommendation, SourceItem } from './types'

export function ratingStyle(rating: number | string) {
  const r = typeof rating === 'number' ? rating : parseInt(String(rating), 10) || 3
  if (r <= 1)
    return {
      ring: 'border-rose-500/40 bg-rose-500/10',
      starColor: 'text-rose-300',
    }
  if (r === 2)
    return {
      ring: 'border-amber-500/40 bg-amber-500/10',
      starColor: 'text-amber-300',
    }
  if (r === 3)
    return {
      ring: 'border-muted-foreground/40 bg-muted-foreground/10',
      starColor: 'text-muted-foreground',
    }
  if (r === 4)
    return {
      ring: 'border-emerald-400/30 bg-emerald-400/5',
      starColor: 'text-emerald-300',
    }
  return {
    ring: 'border-emerald-500/40 bg-emerald-500/10',
    starColor: 'text-emerald-400',
  }
}

export function sentimentBadge(
  sentiment: string,
): { label: string; cls: string } | null {
  const s = (sentiment || '').toLowerCase()
  if (s === 'positive')
    return { label: 'positive', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' }
  if (s === 'negative')
    return { label: 'negative', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' }
  if (s === 'neutral')
    return { label: 'neutral', cls: 'bg-muted-foreground/15 text-muted-foreground border-border' }
  return null
}

export function chatAnswerToText(content: string, sources?: SourceItem[]): string {
  const lines: string[] = ['ANSWER', content, '']
  if (sources && sources.length) {
    lines.push(`SOURCES (${sources.length})`)
    sources.forEach((s, i) => {
      lines.push(`  [${i + 1}] ★${s.rating} · ${s.sentiment}: ${s.text}`)
    })
  }
  return lines.join('\n')
}

export const TOOL_META: Record<
  string,
  { icon: typeof MessageSquareText; colorClass: string; bgClass: string; label: string }
> = {
  review_qa: {
    icon: MessageSquareText,
    colorClass: 'text-blue-400',
    bgClass: 'bg-blue-500/10 border-blue-500/30',
    label: 'review_qa',
  },
  predict_return_risk: {
    icon: AlertTriangle,
    colorClass: 'text-rose-400',
    bgClass: 'bg-rose-500/10 border-rose-500/30',
    label: 'predict_return_risk',
  },
  competitor_search: {
    icon: GitCompare,
    colorClass: 'text-purple-400',
    bgClass: 'bg-purple-500/10 border-purple-500/30',
    label: 'competitor_search',
  },
  price_history: {
    icon: LineChart,
    colorClass: 'text-emerald-400',
    bgClass: 'bg-emerald-500/10 border-emerald-500/30',
    label: 'price_history',
  },
  trend_signal: {
    icon: TrendingUp,
    colorClass: 'text-amber-400',
    bgClass: 'bg-amber-500/10 border-amber-500/30',
    label: 'trend_signal',
  },
}

export function toolMeta(name: string) {
  return (
    TOOL_META[name] || {
      icon: Wrench,
      colorClass: 'text-muted-foreground',
      bgClass: 'bg-card border-border',
      label: name,
    }
  )
}

export function decisionStyle(d: Recommendation['decision']) {
  switch (d) {
    case 'go':
      return {
        label: 'GO',
        textClass: 'text-emerald-300',
        strokeClass: 'stroke-emerald-500',
        borderLeftClass: 'border-l-emerald-500',
        tagline: 'Action plan ready',
      }
    case 'no_go':
      return {
        label: 'NO-GO',
        textClass: 'text-rose-300',
        strokeClass: 'stroke-rose-500',
        borderLeftClass: 'border-l-rose-500',
        tagline: 'Decline this option',
      }
    case 'needs_more_data':
      return {
        label: 'MORE DATA',
        textClass: 'text-amber-300',
        strokeClass: 'stroke-amber-500',
        borderLeftClass: 'border-l-amber-500',
        tagline: 'Insufficient evidence',
      }
  }
}

export function recommendationToText(rec: Recommendation): string {
  const lines: string[] = [
    `DECISION: ${rec.decision.toUpperCase().replace('_', ' ')}`,
    `CONFIDENCE: ${Math.round(rec.confidence * 100)}%`,
    '',
    'SUMMARY',
    rec.summary,
    '',
  ]
  if (rec.reasoning_steps.length) {
    lines.push('REASONING')
    rec.reasoning_steps.forEach((s, i) => lines.push(`  ${i + 1}. ${s}`))
    lines.push('')
  }
  if (rec.evidence.length) {
    lines.push('EVIDENCE')
    rec.evidence.forEach((e, i) => {
      lines.push(`  [${i + 1}] ${e.tool} (rel ${Math.round(e.relevance * 100)}%): ${e.snippet}`)
    })
    lines.push('')
  }
  if (rec.risks.length) {
    lines.push('RISKS')
    rec.risks.forEach((r) => lines.push(`  - ${r}`))
    lines.push('')
  }
  if (rec.suggested_next_actions.length) {
    lines.push('SUGGESTED NEXT ACTIONS')
    rec.suggested_next_actions.forEach((a) => lines.push(`  - ${a}`))
  }
  return lines.join('\n')
}
