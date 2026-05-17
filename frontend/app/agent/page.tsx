'use client'
import { Suspense, useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Send,
  Sparkles,
  Wrench,
  CheckCircle2,
  Loader2,
  AlertCircle,
  ListChecks,
  ShieldAlert,
  ArrowRight,
  RotateCw,
  MessageSquareText,
  AlertTriangle,
  GitCompare,
  LineChart,
  TrendingUp,
  Copy,
  Check,
  ChevronDown,
} from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Use the mock endpoint by default while the live agent is rate-limited.
// Toggle to the real endpoint by setting NEXT_PUBLIC_AGENT_LIVE=true.
const AGENT_ENDPOINT =
  process.env.NEXT_PUBLIC_AGENT_LIVE === 'true' ? '/agent/query' : '/agent/query/mock'

const SAMPLE_QUERIES = [
  { label: 'Why are returns spiking?', icon: '↩' },
  { label: 'Should I launch a noise-canceling variant?', icon: '🆕' },
  { label: 'How do I position against competitors?', icon: '🎯' },
  { label: "What's hurting my conversion rate?", icon: '📉' },
]

// ── Types matching backend event shapes ──────────────────────────────────────

type EvidenceItem = { tool: string; snippet: string; relevance: number }

type Recommendation = {
  decision: 'go' | 'no_go' | 'needs_more_data'
  confidence: number
  summary: string
  reasoning_steps: string[]
  evidence: EvidenceItem[]
  risks: string[]
  suggested_next_actions: string[]
}

type TraceStep =
  | { kind: 'node_started'; node: string; label: string; ts: number }
  | { kind: 'plan_ready'; query_type: string; plan: string[]; ts: number }
  | { kind: 'tool_call'; tool: string; args: Record<string, unknown>; ts: number }
  | { kind: 'tool_result'; tool: string; preview: string; ts: number }
  | { kind: 'executor_thought'; content: string; ts: number }
  | { kind: 'replan'; reason: string; ts: number }
  | { kind: 'error'; message: string; ts: number }
  | { kind: 'done'; ts: number }

// ── Helpers ──────────────────────────────────────────────────────────────────

// Per-tool icon + color metadata. Drives both the trace timeline icons and
// the evidence-card icons so each tool reads consistently across the page.
const TOOL_META: Record<
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

function toolMeta(name: string) {
  return (
    TOOL_META[name] || {
      icon: Wrench,
      colorClass: 'text-muted-foreground',
      bgClass: 'bg-card border-border',
      label: name,
    }
  )
}

function decisionStyle(d: Recommendation['decision']) {
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

function recommendationToText(rec: Recommendation): string {
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

// ── SSE Parser ───────────────────────────────────────────────────────────────

async function* readSSE(response: Response): AsyncGenerator<{ event: string; data: any }> {
  const reader = response.body?.getReader()
  if (!reader) return

  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) return
    buf += decoder.decode(value, { stream: true })

    let sepIdx: number
    while ((sepIdx = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, sepIdx)
      buf = buf.slice(sepIdx + 2)

      let eventName = 'message'
      let dataStr = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
      }
      if (dataStr) {
        try {
          yield { event: eventName, data: JSON.parse(dataStr) }
        } catch {
          yield { event: eventName, data: { raw: dataStr } }
        }
      }
    }
  }
}

// ── Confidence ring ──────────────────────────────────────────────────────────

function ConfidenceRing({
  confidence,
  decision,
}: {
  confidence: number
  decision: Recommendation['decision']
}) {
  const { strokeClass, textClass } = decisionStyle(decision)
  // Geometry: 64x64 viewBox, radius 26, stroke-width 5
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

// ── Recommendation card ──────────────────────────────────────────────────────

function RecommendationCard({
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
      {/* Header: confidence ring + decision word + copy button */}
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

// ── Trace panel ──────────────────────────────────────────────────────────────

function TraceRow({ step, inFlight }: { step: TraceStep; inFlight: boolean }) {
  switch (step.kind) {
    case 'node_started':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          {inFlight ? (
            <Loader2 className="w-3.5 h-3.5 mt-0.5 text-blue-400 animate-spin shrink-0" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
          )}
          <div className="text-xs">
            <span className="text-foreground font-medium">{step.node}</span>
            <span className="text-muted-foreground ml-2">{step.label}</span>
          </div>
        </div>
      )
    case 'plan_ready':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <ListChecks className="w-3.5 h-3.5 mt-0.5 text-purple-400 shrink-0" />
          <div className="text-xs space-y-0.5 min-w-0">
            <div className="text-muted-foreground">Plan ({step.query_type}):</div>
            <div className="flex flex-wrap gap-1">
              {step.plan.map((t, i) => {
                const meta = toolMeta(t)
                return (
                  <code
                    key={i}
                    className={`text-[10px] bg-background-secondary px-1.5 py-0.5 rounded font-mono border ${meta.bgClass} ${meta.colorClass}`}
                  >
                    {t}
                  </code>
                )
              })}
            </div>
          </div>
        </div>
      )
    case 'tool_call': {
      const meta = toolMeta(step.tool)
      const Icon = meta.icon
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <div
            className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 mt-0 ${meta.bgClass}`}
          >
            <Icon className={`w-3 h-3 ${meta.colorClass}`} />
          </div>
          <div className="text-xs text-foreground flex-1 min-w-0">
            calling <code className={`font-mono ${meta.colorClass}`}>{step.tool}</code>
            {step.args && Object.keys(step.args).length > 0 && (
              <span className="text-muted-foreground ml-1 break-words">
                ({JSON.stringify(step.args).slice(0, 80)})
              </span>
            )}
          </div>
        </div>
      )
    }
    case 'tool_result': {
      const meta = toolMeta(step.tool)
      const Icon = meta.icon
      return (
        <details className="py-1.5 group animate-in fade-in slide-in-from-left-2 duration-300">
          <summary className="flex items-start gap-2 cursor-pointer list-none select-none">
            <div
              className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 mt-0 ${meta.bgClass}`}
            >
              <CheckCircle2 className={`w-3 h-3 ${meta.colorClass}`} />
            </div>
            <div className="text-xs text-muted-foreground flex-1 min-w-0">
              <span className="text-foreground font-medium">{step.tool}</span> returned
              <ChevronDown className="w-3 h-3 inline ml-1 transition group-open:rotate-180" />
            </div>
          </summary>
          <div className="text-[11px] text-muted-foreground mt-1 ml-7 break-words whitespace-pre-wrap font-mono bg-background-secondary p-2 rounded border border-border">
            {step.preview}
          </div>
        </details>
      )
    }
    case 'executor_thought':
      return (
        <div className="flex items-start gap-2 py-1.5 pl-7 animate-in fade-in slide-in-from-left-2 duration-300">
          <div className="text-xs text-muted-foreground italic">{step.content}</div>
        </div>
      )
    case 'replan':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <RotateCw className="w-3.5 h-3.5 mt-0.5 text-amber-400 shrink-0" />
          <div className="text-xs text-amber-300">Re-plan: {step.reason}</div>
        </div>
      )
    case 'error':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-rose-400 shrink-0" />
          <div className="text-xs text-rose-300 break-all">{step.message}</div>
        </div>
      )
    case 'done':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
          <div className="text-xs text-emerald-300 font-medium">Done</div>
        </div>
      )
  }
}

// 3-phase preview rendered when the trace is empty — foreshadows the
// Planner / Executor / Synthesizer flow so users learn the structure
// before they click anything.
function TracePreview() {
  return (
    <div className="space-y-3 opacity-50">
      <div className="flex items-start gap-2">
        <ListChecks className="w-3.5 h-3.5 mt-0.5 text-purple-400 shrink-0" />
        <div className="text-xs">
          <span className="text-foreground font-medium">Planner</span>
          <span className="text-muted-foreground ml-2">picks the research tools</span>
        </div>
      </div>
      <div className="flex items-start gap-2">
        <Wrench className="w-3.5 h-3.5 mt-0.5 text-blue-400 shrink-0" />
        <div className="text-xs">
          <span className="text-foreground font-medium">Executor</span>
          <span className="text-muted-foreground ml-2">runs the tools</span>
        </div>
      </div>
      <div className="flex items-start gap-2">
        <Sparkles className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
        <div className="text-xs">
          <span className="text-foreground font-medium">Synthesizer</span>
          <span className="text-muted-foreground ml-2">writes the recommendation</span>
        </div>
      </div>
      <div className="pt-2 text-[10px] text-muted-foreground italic">
        Each step streams in live as the agent runs.
      </div>
    </div>
  )
}

function TracePanel({
  steps,
  isStreaming,
}: {
  steps: TraceStep[]
  isStreaming: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [steps.length])

  const lastIdx = steps.length - 1
  const elapsedMs =
    steps.length >= 2 ? steps[steps.length - 1].ts - steps[0].ts : 0
  const elapsedSec = (elapsedMs / 1000).toFixed(1)

  return (
    <div className="bg-card border border-border rounded-xl flex flex-col min-h-0 h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-purple-400" />
        <span className="text-sm font-medium text-foreground">Agent trace</span>
        {steps.length > 0 && (
          <span className="text-xs text-muted-foreground ml-auto">{steps.length} events</span>
        )}
      </div>
      <div ref={ref} className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
        {steps.length === 0 ? (
          <TracePreview />
        ) : (
          <div className="divide-y divide-border/40">
            {steps.map((s, i) => (
              <div key={i} id={`trace-row-${i}`} className="transition rounded">
                <TraceRow step={s} inFlight={isStreaming && i === lastIdx} />
              </div>
            ))}
          </div>
        )}
      </div>
      {steps.length > 0 && (
        <div className="px-4 py-2 border-t border-border text-[10px] text-muted-foreground flex items-center justify-between font-mono">
          <span>{steps.length} events</span>
          <span>{elapsedSec}s elapsed</span>
        </div>
      )}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

interface ChatMessage {
  role: 'user' | 'assistant'
  content?: string
  recommendation?: Recommendation
  error?: string
}

function AgentPageContent() {
  const searchParams = useSearchParams()
  const asin = searchParams.get('asin') || 'B08XPWDSWW'
  const [productName, setProductName] = useState(asin)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [trace, setTrace] = useState<TraceStep[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const cached = sessionStorage.getItem(`analysis_${asin}`)
    if (cached) {
      try {
        const data = JSON.parse(cached)
        setProductName(data.product_name || asin)
      } catch {}
    }
  }, [asin])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  // Keyboard shortcuts:
  //   Cmd+K / Ctrl+K  → focus the input
  //   Esc             → clear + blur the input (only when input is focused)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
        return
      }
      if (e.key === 'Escape' && !loading) {
        if (document.activeElement === inputRef.current) {
          setInput('')
          inputRef.current?.blur()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [loading])

  // Evidence card → trace row scroll-and-highlight. Walks the trace in
  // reverse to find the latest tool_result matching the clicked tool.
  const handleEvidenceClick = useCallback(
    (tool: string) => {
      for (let i = trace.length - 1; i >= 0; i--) {
        const step = trace[i]
        if (step.kind === 'tool_result' && step.tool === tool) {
          const el = document.getElementById(`trace-row-${i}`)
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' })
            el.classList.add('ring-2', 'ring-blue-400/60')
            setTimeout(() => {
              el.classList.remove('ring-2', 'ring-blue-400/60')
            }, 900)
          }
          return
        }
      }
    },
    [trace]
  )

  const submit = async (query: string) => {
    if (!query.trim() || loading) return
    setInput('')
    setLoading(true)
    setTrace([])
    setMessages((prev) => [...prev, { role: 'user', content: query }])

    try {
      const res = await fetch(`${API_URL}${AGENT_ENDPOINT}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asin, query }),
      })
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`)
      }

      let recommendation: Recommendation | null = null
      let errored: string | null = null

      for await (const { event, data } of readSSE(res)) {
        const now = Date.now()
        switch (event) {
          case 'started':
            if (data?.product_name) setProductName(data.product_name)
            break
          case 'node_started':
            setTrace((p) => [
              ...p,
              { kind: 'node_started', node: data.node, label: data.label, ts: now },
            ])
            break
          case 'plan_ready':
            setTrace((p) => [
              ...p,
              { kind: 'plan_ready', query_type: data.query_type, plan: data.plan, ts: now },
            ])
            break
          case 'tool_call':
            setTrace((p) => [
              ...p,
              { kind: 'tool_call', tool: data.tool, args: data.args || {}, ts: now },
            ])
            break
          case 'tool_result':
            setTrace((p) => [
              ...p,
              {
                kind: 'tool_result',
                tool: data.tool,
                preview: data.result_preview || '',
                ts: now,
              },
            ])
            break
          case 'executor_thought':
            setTrace((p) => [
              ...p,
              { kind: 'executor_thought', content: data.content, ts: now },
            ])
            break
          case 'replan':
            setTrace((p) => [...p, { kind: 'replan', reason: data.reason, ts: now }])
            break
          case 'recommendation':
            recommendation = data as Recommendation
            break
          case 'error':
            errored = data?.message || 'Unknown error'
            setTrace((p) => [...p, { kind: 'error', message: errored!, ts: now }])
            break
          case 'done':
            setTrace((p) => [...p, { kind: 'done', ts: now }])
            break
          case 'node_completed':
            // intentional no-op — already implicit when next node starts
            break
        }
      }

      setMessages((prev) => [
        ...prev,
        errored
          ? { role: 'assistant', error: errored }
          : recommendation
            ? { role: 'assistant', recommendation }
            : { role: 'assistant', error: 'Agent finished without a recommendation' },
      ])
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', error: e?.message || 'Network failure — is the backend running?' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col w-full h-full min-h-0 p-4 md:p-6">
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4 min-h-0">
        {/* Chat pane */}
        <div className="flex flex-col min-h-0">
          {/* Sample queries strip (chat-column only) */}
          <div className="mb-4">
            <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
              Try a query
            </p>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {SAMPLE_QUERIES.map((q) => (
                <button
                  key={q.label}
                  onClick={() => submit(q.label)}
                  disabled={loading}
                  className="flex-none text-xs px-3 py-2 rounded-lg border border-border hover:border-blue-500 text-muted-foreground hover:text-foreground transition-colors whitespace-nowrap disabled:opacity-50"
                >
                  <span className="mr-1.5">{q.icon}</span>
                  {q.label}
                </button>
              ))}
            </div>
          </div>

          {messages.length === 0 && !loading ? (
            // Empty state — not inside the overflow-y-auto container so it
            // never triggers a scrollbar.
            <div className="flex-1 flex flex-col items-center justify-center text-center px-4 min-h-0">
              <Sparkles className="w-8 h-8 text-purple-400/60 mb-3" />
              <p className="text-sm text-muted-foreground max-w-md">
                Ask the Copilot a question about this product. It will plan a research path,
                call the right tools, and return a structured recommendation with cited evidence.
              </p>
              <p className="text-[11px] text-muted-foreground/70 mt-3">
                Press <kbd className="px-1.5 py-0.5 text-[10px] bg-card border border-border rounded font-mono">⌘K</kbd> to focus the input
              </p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto min-h-0 space-y-4 pr-1">
              {messages.map((m, i) => {
                if (m.role === 'user') {
                  return (
                    <div key={i} className="flex justify-end">
                      <div className="max-w-[80%] rounded-xl px-4 py-3 text-sm bg-blue-600 text-white rounded-br-sm">
                        {m.content}
                      </div>
                    </div>
                  )
                }
                if (m.error) {
                  return (
                    <div key={i} className="flex justify-start">
                      <div className="max-w-[80%] rounded-xl px-4 py-3 text-sm bg-rose-500/10 border border-rose-500/40 text-rose-300">
                        {m.error}
                      </div>
                    </div>
                  )
                }
                if (m.recommendation) {
                  return (
                    <div key={i} className="flex justify-start">
                      <div className="max-w-[95%] w-full">
                        <RecommendationCard
                          rec={m.recommendation}
                          onEvidenceClick={handleEvidenceClick}
                        />
                      </div>
                    </div>
                  )
                }
                return null
              })}

              {loading && (
                <div className="flex justify-start">
                  <div className="bg-card border border-border rounded-xl px-4 py-3">
                    <div className="flex gap-1">
                      <span
                        className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce"
                        style={{ animationDelay: '0ms' }}
                      />
                      <span
                        className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce"
                        style={{ animationDelay: '150ms' }}
                      />
                      <span
                        className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce"
                        style={{ animationDelay: '300ms' }}
                      />
                    </div>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}

          {/* Input */}
          <div className="border-t border-border pt-4 mt-2">
            <p className="text-xs text-muted-foreground text-center mb-2">
              Copilot uses 5 tools (RAG, return-risk model, competitors, prices, trends).
              {AGENT_ENDPOINT.endsWith('/mock') && (
                <span className="ml-2 px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 text-[10px] uppercase tracking-wider">
                  mock mode
                </span>
              )}
            </p>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && submit(input)}
                  placeholder="Ask the Copilot..."
                  disabled={loading}
                  className="peer w-full bg-card border border-border rounded-xl px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-blue-500 disabled:opacity-50"
                />
                <kbd className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground bg-background-secondary border border-border rounded px-1.5 py-0.5 pointer-events-none font-mono peer-focus:opacity-0 transition-opacity">
                  ⌘K
                </kbd>
              </div>
              <button
                onClick={() => submit(input)}
                disabled={!input.trim() || loading}
                className="w-10 h-10 rounded-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center transition-colors"
                aria-label="Send"
              >
                <Send className="w-4 h-4 text-white" />
              </button>
            </div>
          </div>
        </div>

        {/* Trace pane (right; collapses below on mobile) */}
        <div className="min-h-[300px] lg:min-h-0">
          <TracePanel steps={trace} isStreaming={loading} />
        </div>
      </div>
    </div>
  )
}

export default function AgentPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-screen text-muted-foreground">
          Loading...
        </div>
      }
    >
      <AgentPageContent />
    </Suspense>
  )
}
