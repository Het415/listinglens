'use client'
import { Suspense, useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams, useRouter, usePathname } from 'next/navigation'
import { Send, Sparkles, Zap, Bot, Trash2, ChevronDown } from 'lucide-react'
import { AssistantMessage } from '@/components/assistant/AssistantMessage'
import { RecommendationCard } from '@/components/assistant/RecommendationCard'
import { TracePanel } from '@/components/assistant/TracePanel'
import {
  useAssistant,
  submitAssistant,
  clearAssistant,
  type Mode,
} from '@/components/assistant/assistantStore'
import { DEMO_ASIN } from '@/lib/demo-config'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const SAMPLE_QUERIES: Record<Mode, { label: string; icon: string }[]> = {
  quick: [
    { label: 'What do 1-star reviews say?', icon: '⭐' },
    { label: 'Customer complaints about battery?', icon: '🔋' },
    { label: 'Which features do buyers love?', icon: '💚' },
    { label: 'Common quality issues mentioned?', icon: '⚠️' },
  ],
  copilot: [
    { label: 'Should I launch a noise-canceling variant?', icon: '🆕' },
    { label: 'Why are returns spiking?', icon: '↩' },
    { label: 'How do I position against competitors?', icon: '🎯' },
    { label: "What's hurting my conversion rate?", icon: '📉' },
  ],
}

function ModeToggle({
  mode,
  onChange,
  disabled,
}: {
  mode: Mode
  onChange: (m: Mode) => void
  disabled?: boolean
}) {
  return (
    <div
      role="tablist"
      aria-label="Assistant mode"
      className="inline-flex items-center gap-0.5 rounded-full border border-border bg-background-secondary p-0.5"
    >
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'quick'}
        onClick={() => onChange('quick')}
        disabled={disabled}
        title="Fast grounded Q&A — RAG over reviews, ~5s"
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors disabled:opacity-50 ${
          mode === 'quick'
            ? 'bg-teal-500/15 text-teal-300 border border-teal-500/40'
            : 'text-muted-foreground hover:text-foreground'
        }`}
      >
        <Zap className="w-3.5 h-3.5" />
        Quick Q&A
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'copilot'}
        onClick={() => onChange('copilot')}
        disabled={disabled}
        title="Multi-step Copilot — Planner → Executor → Synthesizer, ~10-30s"
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors disabled:opacity-50 ${
          mode === 'copilot'
            ? 'bg-purple-500/15 text-purple-300 border border-purple-500/40'
            : 'text-muted-foreground hover:text-foreground'
        }`}
      >
        <Bot className="w-3.5 h-3.5" />
        Copilot
      </button>
    </div>
  )
}

function AssistantPageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const asin = searchParams.get('asin') || DEMO_ASIN
  // Pre-filled question + mode from dashboard deep-links
  // (e.g. /assistant?asin=...&q=How+do+I...&mode=copilot).
  const prefillQuery = searchParams.get('q')
  const prefillModeRaw = searchParams.get('mode')
  const prefillMode: Mode | null =
    prefillModeRaw === 'quick' || prefillModeRaw === 'copilot' ? prefillModeRaw : null

  const [productName, setProductName] = useState(asin)
  const [mode, setMode] = useState<Mode>(prefillMode ?? 'quick')
  // messages / trace / loading live in a module-scoped store keyed by ASIN, so
  // an in-flight run survives navigating away from this page and is still here
  // (streaming or finished) when the user comes back. See assistantStore.ts.
  const { messages, trace, loading } = useAssistant(asin)
  const [input, setInput] = useState('')
  // Mobile trace dropdown is controlled — closed by default, auto-opens
  // while streaming so users see progress, user can close again any time.
  const [traceOpen, setTraceOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // Tracks the last `?q=` we auto-submitted, so navigating back to a deep-link
  // URL after URL cleanup doesn't replay the same question. A new deep-link
  // (different `q`) will still fire because the value changes.
  const lastAutoSubmittedRef = useRef<string | null>(null)

  useEffect(() => {
    // Reset first so the previous product's name never lingers when the ASIN
    // changes without a remount (same route, new ?asin=).
    setProductName(asin)
    const cached = sessionStorage.getItem(`analysis_${asin}`)
    if (cached) {
      try {
        const data = JSON.parse(cached)
        if (data?.product_name) setProductName(data.product_name)
      } catch {}
    }
  }, [asin])

  const clearChat = useCallback(() => {
    clearAssistant(asin)
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
    [trace],
  )

  // Thin wrapper around the store. The actual fetch + SSE loop runs in module
  // scope (assistantStore.ts) so it isn't bound to this component's lifecycle —
  // navigating away no longer cancels it, and the answer is persisted on return.
  const submit = useCallback(
    (query: string, overrideMode?: Mode) => {
      const trimmed = query.trim()
      if (!trimmed || loading) return
      setInput('')
      // Pass the mode explicitly: deep-link auto-submit sets mode and submits
      // back-to-back, and setState hasn't flushed yet inside this closure.
      submitAssistant(asin, trimmed, overrideMode ?? mode, API_URL)
    },
    [asin, mode, loading],
  )

  // Auto-submit support for dashboard deep-links: /assistant?asin=…&q=…&mode=copilot.
  // Fires once per unique `q` value. The store appends to whatever history is
  // already loaded for this ASIN, so there's no hydration race to wait on.
  // After submit we strip `q`/`mode` from the URL so back-button doesn't replay.
  useEffect(() => {
    if (!prefillQuery || loading) return
    if (lastAutoSubmittedRef.current === prefillQuery) return

    if (prefillMode && prefillMode !== mode) {
      setMode(prefillMode)
    }
    lastAutoSubmittedRef.current = prefillQuery
    submit(prefillQuery, prefillMode ?? mode)

    const params = new URLSearchParams(searchParams.toString())
    params.delete('q')
    params.delete('mode')
    const cleaned = params.toString()
    router.replace(cleaned ? `${pathname}?${cleaned}` : pathname, { scroll: false })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillQuery, prefillMode])

  const samples = SAMPLE_QUERIES[mode]

  return (
    <div className="flex flex-col w-full h-full min-h-0 p-4 md:p-6">
      <div className="flex-1 grid grid-cols-1 grid-rows-[auto_1fr] lg:grid-cols-[1fr_360px] lg:grid-rows-1 gap-4 min-h-0">
        <div className="flex flex-col min-h-0">
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2 gap-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Try a question
              </p>
              <div className="flex items-center gap-2">
                {messages.length > 0 && (
                  <button
                    type="button"
                    onClick={clearChat}
                    disabled={loading}
                    title="Clear chat history for this product"
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground hover:bg-background-secondary border border-transparent hover:border-border transition disabled:opacity-50"
                  >
                    <Trash2 className="w-3 h-3" />
                    Clear
                  </button>
                )}
                <ModeToggle mode={mode} onChange={setMode} disabled={loading} />
              </div>
            </div>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {samples.map((q) => (
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
                {mode === 'quick' ? (
                  <>
                    <strong className="text-foreground">Quick Q&amp;A</strong> — grounded
                    answers from this product&apos;s reviews with cited sources. Fast (~5s).
                  </>
                ) : (
                  <>
                    <strong className="text-foreground">Copilot</strong> — the agent plans
                    a research path, calls multiple tools, and returns a structured
                    recommendation with cited evidence. (~10–30s)
                  </>
                )}
              </p>
              <p className="text-[11px] text-muted-foreground/70 mt-3">
                Press{' '}
                <kbd className="px-1.5 py-0.5 text-[10px] bg-card border border-border rounded font-mono">
                  ⌘K
                </kbd>{' '}
                to focus the input
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
                if (m.content !== undefined) {
                  return (
                    <div key={i} className="flex justify-start">
                      <AssistantMessage msg={m} />
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
              {mode === 'quick'
                ? 'Quick Q&A — grounded in '
                : 'Copilot uses 5 tools — '}
              {productName} reviews.
            </p>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && submit(input)}
                  placeholder={
                    mode === 'quick'
                      ? 'Ask about this product\'s reviews...'
                      : 'Ask the Copilot a strategic question...'
                  }
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

        {/* Trace pane.
            - Desktop (lg+): a fixed 360px right rail rendered inline.
            - Mobile / tablet: collapses into a dropdown above the chat —
              like Claude / Gemini's "thinking" thread — so the full-height
              trace panel doesn't crowd a short viewport. Uses controlled
              state instead of <details> because some global CSS in this
              stack prevented native <details> from collapsing its body. */}
        <div className="lg:hidden order-first bg-card border border-border rounded-xl overflow-hidden">
          <button
            type="button"
            onClick={() => setTraceOpen((v) => !v)}
            aria-expanded={traceOpen || loading}
            className="w-full flex items-center gap-2 px-4 py-3 cursor-pointer text-left"
          >
            <Sparkles className="w-4 h-4 text-purple-400" />
            <span className="text-sm font-medium text-foreground">Agent trace</span>
            <span className="text-xs text-muted-foreground ml-auto">
              {trace.length === 0
                ? 'idle'
                : `${trace.length} event${trace.length === 1 ? '' : 's'}`}
            </span>
            <ChevronDown
              className={`w-4 h-4 text-muted-foreground transition ${
                traceOpen || loading ? 'rotate-180' : ''
              }`}
            />
          </button>
          {(traceOpen || loading) && (
            <div className="border-t border-border h-[260px]">
              <TracePanel steps={trace} isStreaming={loading} hideHeader />
            </div>
          )}
        </div>

        {/* Desktop trace rail — unchanged. */}
        <div className="hidden lg:block min-h-0">
          <TracePanel steps={trace} isStreaming={loading} />
        </div>
      </div>
    </div>
  )
}

export default function AssistantPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-screen text-muted-foreground">
          Loading...
        </div>
      }
    >
      <AssistantPageContent />
    </Suspense>
  )
}
