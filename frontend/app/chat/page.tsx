'use client'
import { Suspense, useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Send,
  Sparkles,
  Star,
  Copy,
  Check,
  ChevronDown,
} from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const SUGGESTED = [
  "Why are customers returning this product?",
  "What do 1-star reviewers complain about most?",
  "Which features do buyers love the most?",
  "What are the most common quality issues mentioned?",
  "How do customers describe the product after long-term use?",
]

interface SourceItem {
  text: string
  rating: number | string
  sentiment: string
  score: number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceItem[]
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function ratingStyle(rating: number | string) {
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

function sentimentBadge(sentiment: string): { label: string; cls: string } | null {
  const s = (sentiment || '').toLowerCase()
  if (s === 'positive')
    return { label: 'positive', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' }
  if (s === 'negative')
    return { label: 'negative', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' }
  if (s === 'neutral')
    return { label: 'neutral', cls: 'bg-muted-foreground/15 text-muted-foreground border-border' }
  return null
}

function chatAnswerToText(content: string, sources?: SourceItem[]): string {
  const lines: string[] = ['ANSWER', content, '']
  if (sources && sources.length) {
    lines.push(`SOURCES (${sources.length})`)
    sources.forEach((s, i) => {
      lines.push(`  [${i + 1}] ★${s.rating} · ${s.sentiment}: ${s.text}`)
    })
  }
  return lines.join('\n')
}

// ── Assistant message ────────────────────────────────────────────────────────

function AssistantMessage({ msg }: { msg: Message }) {
  const [copied, setCopied] = useState(false)
  const [allOpen, setAllOpen] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(chatAnswerToText(msg.content, msg.sources))
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable — silently ignore
    }
  }

  return (
    <div className="max-w-[80%] rounded-xl px-4 py-3 text-sm bg-card border border-border text-foreground rounded-bl-sm border-l-2 border-l-teal-500 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
          <Sparkles className="w-3 h-3 text-teal-400" />
          Grounded answer
        </div>
        <button
          onClick={handleCopy}
          aria-label="Copy answer"
          title="Copy answer + sources"
          className="shrink-0 w-6 h-6 rounded border border-border bg-background-secondary hover:border-teal-500/60 hover:text-foreground text-muted-foreground transition flex items-center justify-center"
        >
          {copied ? (
            <Check className="w-3 h-3 text-emerald-400" />
          ) : (
            <Copy className="w-3 h-3" />
          )}
        </button>
      </div>

      <div className="leading-relaxed">{msg.content}</div>

      {msg.sources && msg.sources.length > 0 && (
        <details className="mt-3 group" open={allOpen} onToggle={(e) => setAllOpen((e.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground transition list-none flex items-center gap-1.5">
            <ChevronDown className="w-3 h-3 transition group-open:rotate-180" />
            <span>Sources ({msg.sources.length})</span>
          </summary>
          <div className="mt-2 space-y-1.5">
            {msg.sources.map((s, i) => {
              const rstyle = ratingStyle(s.rating)
              const sbadge = sentimentBadge(s.sentiment)
              return (
                <div
                  key={i}
                  className={`rounded-lg border p-2.5 ${rstyle.ring}`}
                >
                  <div className="flex items-center gap-2 mb-1 text-[10px] uppercase tracking-wider">
                    <span className="text-muted-foreground font-medium">
                      Source {i + 1} / {msg.sources!.length}
                    </span>
                    <div className="flex items-center gap-0.5 ml-auto">
                      <Star className={`w-3 h-3 fill-current ${rstyle.starColor}`} />
                      <span className={`font-mono ${rstyle.starColor}`}>{s.rating}</span>
                    </div>
                    {sbadge && (
                      <span
                        className={`px-1.5 py-0.5 rounded text-[9px] border ${sbadge.cls}`}
                      >
                        {sbadge.label}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground leading-snug">{s.text}</p>
                </div>
              )
            })}
          </div>
        </details>
      )}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

function ChatPageContent() {
  const searchParams = useSearchParams()
  const asin = searchParams.get('asin') || 'B08XPWDSWW'
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [productName, setProductName] = useState(asin)
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
  }, [messages])

  // Keyboard shortcuts — match the /agent page:
  //   Cmd+K / Ctrl+K → focus + select the input
  //   Esc            → clear + blur the input (only when input is focused)
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

  const sendMessage = useCallback(
    async (question: string) => {
      if (!question.trim() || loading) return
      setInput('')
      setLoading(true)

      const userMsg: Message = { role: 'user', content: question }
      setMessages((prev) => [...prev, userMsg])

      try {
        const res = await fetch(`${API_URL}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ asin, question }),
        })
        const data = await res.json()
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.answer,
            sources: data.sources,
          },
        ])
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: 'Failed to get answer. Make sure backend is running.',
          },
        ])
      } finally {
        setLoading(false)
      }
    },
    [asin, loading]
  )

  return (
    <div className="flex flex-col w-full h-full min-h-0 p-4 md:p-6">
      {/* Top strip: product context + suggested questions */}
      <div className="flex items-start justify-between gap-6 mb-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{productName}</p>
          <p className="text-xs text-muted-foreground truncate">{asin}</p>
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide hidden sm:block">
            Suggested Questions
          </p>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {SUGGESTED.map((q, i) => (
              <button
                key={i}
                onClick={() => sendMessage(q)}
                disabled={loading}
                className="flex-none text-xs px-3 py-2 rounded-lg border border-border hover:border-blue-500 text-muted-foreground hover:text-foreground transition-colors whitespace-nowrap disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chat messages */}
      <div className="flex-1 overflow-y-auto space-y-4 min-h-0">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <Sparkles className="w-7 h-7 text-teal-400/60 mb-3" />
            <p className="text-sm text-muted-foreground max-w-md">
              Ask anything about this product's customer reviews. Answers are grounded
              in the actual review text and cite up to 5 sources per response.
            </p>
            <p className="text-[11px] text-muted-foreground/70 mt-3">
              Press{' '}
              <kbd className="px-1.5 py-0.5 text-[10px] bg-card border border-border rounded font-mono">
                ⌘K
              </kbd>{' '}
              to focus the input
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'user' ? (
              <div className="max-w-[80%] rounded-xl px-4 py-3 text-sm bg-blue-600 text-white rounded-br-sm">
                {msg.content}
              </div>
            ) : (
              <AssistantMessage msg={msg} />
            )}
          </div>
        ))}

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

      {/* Input */}
      <div className="border-t border-border p-4">
        <div className="w-full">
          <p className="text-xs text-muted-foreground text-center mb-2">
            Answers grounded in the {productName} reviews
          </p>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendMessage(input)}
                placeholder="Ask anything about this product's reviews..."
                disabled={loading}
                className="peer w-full bg-card border border-border rounded-xl px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-blue-500 disabled:opacity-50"
              />
              <kbd className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground bg-background-secondary border border-border rounded px-1.5 py-0.5 pointer-events-none font-mono peer-focus:opacity-0 transition-opacity">
                ⌘K
              </kbd>
            </div>
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || loading}
              className="w-10 h-10 rounded-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center transition-colors"
              aria-label="Send"
            >
              <Send className="w-4 h-4 text-white" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-screen text-muted-foreground">
          Loading...
        </div>
      }
    >
      <ChatPageContent />
    </Suspense>
  )
}
