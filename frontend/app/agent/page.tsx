'use client'
import { Suspense, useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import { Send, Sparkles } from 'lucide-react'
import { RecommendationCard } from '@/components/assistant/RecommendationCard'
import { TracePanel } from '@/components/assistant/TracePanel'
import { readSSE } from '@/components/assistant/sse'
import type { Recommendation, TraceStep, ChatMessage } from '@/components/assistant/types'

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
        <div className="flex flex-col min-h-0">
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
