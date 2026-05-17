'use client'
import { Suspense, useState, useEffect, useRef } from 'react'
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

    // Process complete frames (separated by blank line)
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

// ── Recommendation card ──────────────────────────────────────────────────────

function decisionStyle(d: Recommendation['decision']) {
  switch (d) {
    case 'go':
      return { label: 'GO', cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' }
    case 'no_go':
      return { label: 'NO GO', cls: 'bg-rose-500/20 text-rose-300 border-rose-500/40' }
    case 'needs_more_data':
      return { label: 'NEEDS MORE DATA', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/40' }
  }
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const { label, cls } = decisionStyle(rec.decision)
  const [expanded, setExpanded] = useState<number | null>(null)
  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4 border-l-2 border-l-teal-500 animate-in fade-in slide-in-from-bottom-2 duration-500">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <span
          className={`text-xs font-semibold tracking-wide px-2.5 py-1 rounded-md border ${cls}`}
        >
          {label}
        </span>
        <div className="text-xs text-muted-foreground">
          Confidence:{' '}
          <span className="text-foreground font-medium">
            {(rec.confidence * 100).toFixed(0)}%
          </span>
        </div>
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
            {rec.evidence.map((e, i) => (
              <button
                key={i}
                onClick={() => setExpanded(expanded === i ? null : i)}
                className="w-full text-left bg-background-secondary border border-border rounded-lg p-3 hover:border-blue-500/60 transition"
              >
                <div className="flex items-center gap-2 mb-1">
                  <code className="text-[10px] uppercase tracking-wider text-blue-400 font-mono">
                    {e.tool}
                  </code>
                  <span className="text-[10px] text-muted-foreground">
                    rel {Math.round(e.relevance * 100)}%
                  </span>
                </div>
                <p
                  className={`text-xs text-foreground leading-snug ${
                    expanded === i ? '' : 'line-clamp-2'
                  }`}
                >
                  {e.snippet}
                </p>
              </button>
            ))}
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
        <div className="flex items-start gap-2 py-1.5">
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
        <div className="flex items-start gap-2 py-1.5">
          <ListChecks className="w-3.5 h-3.5 mt-0.5 text-purple-400 shrink-0" />
          <div className="text-xs space-y-0.5">
            <div className="text-muted-foreground">
              Plan ({step.query_type}):
            </div>
            <div className="flex flex-wrap gap-1">
              {step.plan.map((t, i) => (
                <code
                  key={i}
                  className="text-[10px] bg-background-secondary text-foreground px-1.5 py-0.5 rounded font-mono"
                >
                  {t}
                </code>
              ))}
            </div>
          </div>
        </div>
      )
    case 'tool_call':
      return (
        <div className="flex items-start gap-2 py-1.5">
          <Wrench className="w-3.5 h-3.5 mt-0.5 text-blue-400 shrink-0" />
          <div className="text-xs text-foreground">
            calling <code className="text-blue-400 font-mono">{step.tool}</code>
            {step.args && Object.keys(step.args).length > 0 && (
              <span className="text-muted-foreground ml-1">
                ({JSON.stringify(step.args).slice(0, 80)})
              </span>
            )}
          </div>
        </div>
      )
    case 'tool_result':
      return (
        <div className="flex items-start gap-2 py-1.5">
          <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
          <div className="text-xs text-muted-foreground">
            <span className="text-foreground">{step.tool}</span> returned:{' '}
            <span className="line-clamp-2">{step.preview.slice(0, 200)}</span>
          </div>
        </div>
      )
    case 'executor_thought':
      return (
        <div className="flex items-start gap-2 py-1.5 pl-5">
          <div className="text-xs text-muted-foreground italic">
            {step.content}
          </div>
        </div>
      )
    case 'replan':
      return (
        <div className="flex items-start gap-2 py-1.5">
          <RotateCw className="w-3.5 h-3.5 mt-0.5 text-amber-400 shrink-0" />
          <div className="text-xs text-amber-300">Re-plan: {step.reason}</div>
        </div>
      )
    case 'error':
      return (
        <div className="flex items-start gap-2 py-1.5">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-rose-400 shrink-0" />
          <div className="text-xs text-rose-300 break-all">{step.message}</div>
        </div>
      )
    case 'done':
      return (
        <div className="flex items-start gap-2 py-1.5">
          <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
          <div className="text-xs text-emerald-300 font-medium">Done</div>
        </div>
      )
  }
}

function TracePanel({ steps, isStreaming }: { steps: TraceStep[]; isStreaming: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [steps.length])

  // Only the LAST event in the trace is "in flight", and only while
  // streaming. Once a newer event arrives (or the stream ends), prior
  // node_started rows flip from spinner to checkmark.
  const lastIdx = steps.length - 1

  return (
    <div className="bg-card border border-border rounded-xl flex flex-col min-h-0 h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-purple-400" />
        <span className="text-sm font-medium text-foreground">Agent trace</span>
        <span className="text-xs text-muted-foreground ml-auto">
          {steps.length} events
        </span>
      </div>
      <div ref={ref} className="flex-1 min-h-0 overflow-y-auto px-4 py-2">
        {steps.length === 0 ? (
          <div className="flex items-center justify-center h-full text-xs text-muted-foreground">
            Trace will appear here when the agent runs
          </div>
        ) : (
          <div className="divide-y divide-border/40">
            {steps.map((s, i) => (
              <TraceRow key={i} step={s} inFlight={isStreaming && i === lastIdx} />
            ))}
          </div>
        )}
      </div>
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
            setTrace((p) => [...p, { kind: 'node_started', node: data.node, label: data.label, ts: now }])
            break
          case 'plan_ready':
            setTrace((p) => [...p, { kind: 'plan_ready', query_type: data.query_type, plan: data.plan, ts: now }])
            break
          case 'tool_call':
            setTrace((p) => [...p, { kind: 'tool_call', tool: data.tool, args: data.args || {}, ts: now }])
            break
          case 'tool_result':
            setTrace((p) => [...p, { kind: 'tool_result', tool: data.tool, preview: data.result_preview || '', ts: now }])
            break
          case 'executor_thought':
            setTrace((p) => [...p, { kind: 'executor_thought', content: data.content, ts: now }])
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
      {/* Two-pane main area: chat (left) + trace (right).
          The page-level header was removed — topbar + sidebar already
          convey 'Copilot' + the product context. Sample-query row now
          lives inside the chat column so it doesn't extend across the
          trace pane. */}
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
            // never triggers a scrollbar. Just a centered flex child filling
            // the remaining vertical space.
            <div className="flex-1 flex flex-col items-center justify-center text-center px-4 min-h-0">
              <Sparkles className="w-8 h-8 text-purple-400/60 mb-3" />
              <p className="text-sm text-muted-foreground max-w-md">
                Ask the Copilot a question about this product. It will plan a
                research path, call the right tools, and return a structured
                recommendation with cited evidence.
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
                        <RecommendationCard rec={m.recommendation} />
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
                      <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
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
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submit(input)}
                placeholder="Ask the Copilot..."
                disabled={loading}
                className="flex-1 bg-card border border-border rounded-xl px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-blue-500 disabled:opacity-50"
              />
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
