'use client'
import { Suspense, useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import { Send, Sparkles } from 'lucide-react'
import { AssistantMessage } from '@/components/assistant/AssistantMessage'
import type { ChatMessage } from '@/components/assistant/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const SUGGESTED = [
  "Why are customers returning this product?",
  "What do 1-star reviewers complain about most?",
  "Which features do buyers love the most?",
  "What are the most common quality issues mentioned?",
  "How do customers describe the product after long-term use?",
]

function ChatPageContent() {
  const searchParams = useSearchParams()
  const asin = searchParams.get('asin') || 'B08XPWDSWW'
  const [messages, setMessages] = useState<ChatMessage[]>([])
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

      const userMsg: ChatMessage = { role: 'user', content: question }
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
    <div className="flex flex-col w-full max-w-3xl h-full min-h-0 p-4 md:p-6">
      <div className="mb-4">
        <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
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
