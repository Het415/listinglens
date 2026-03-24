'use client'
import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import { Send } from 'lucide-react'
import { Logo } from '@/components/logo'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const SUGGESTED = [
  "Why are customers returning this?",
  "What do 1-star reviewers say most?",
  "Which features do buyers love?",
  "What are the most common complaints?",
  "How do customers describe long-term use?",
]

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: any[]
}

export default function ChatPage() {
  const searchParams = useSearchParams()
  const asin = searchParams.get('asin') || 'B08XPWDSWW'
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [productName, setProductName] = useState(asin)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const cached = sessionStorage.getItem(`analysis_${asin}`)
    if (cached) {
      const data = JSON.parse(cached)
      setProductName(data.product_name || asin)
    }
  }, [asin])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async (question: string) => {
    if (!question.trim() || loading) return
    setInput('')
    setLoading(true)

    const userMsg: Message = { role: 'user', content: question }
    setMessages(prev => [...prev, userMsg])

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asin, question }),
      })
      const data = await res.json()
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer,
        sources: data.sources,
      }])
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Failed to get answer. Make sure backend is running.',
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen bg-background">
      {/* Left panel */}
      <div className="w-72 border-r border-border bg-card p-4 flex flex-col gap-4">
        <Logo />
        <div className="rounded-lg border border-border p-3 space-y-1">
          <p className="text-sm font-medium text-foreground">{productName}</p>
          <p className="text-xs text-muted-foreground">{asin}</p>
        </div>
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
            Suggested Questions
          </p>
          <div className="space-y-2">
            {SUGGESTED.map((q, i) => (
              <button
                key={i}
                onClick={() => sendMessage(q)}
                className="w-full text-left text-xs px-3 py-2 rounded-lg border border-border hover:border-blue-500 text-muted-foreground hover:text-foreground transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chat panel */}
      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
              Ask anything about this product's customer reviews
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-xl px-4 py-3 text-sm ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-br-sm'
                  : 'bg-card border border-border text-foreground rounded-bl-sm border-l-2 border-l-teal-500'
              }`}>
                {msg.content}
                {msg.sources && msg.sources.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-muted-foreground cursor-pointer">
                      Sources ({msg.sources.length} reviews)
                    </summary>
                    <div className="mt-1 space-y-1">
                      {msg.sources.slice(0, 2).map((s, j) => (
                        <p key={j} className="text-xs text-muted-foreground border-t border-border pt-1">
                          ★{s.rating} · {s.text.slice(0, 100)}...
                        </p>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-card border border-border rounded-xl px-4 py-3">
                <div className="flex gap-1">
                  <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{animationDelay:'0ms'}}/>
                  <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{animationDelay:'150ms'}}/>
                  <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{animationDelay:'300ms'}}/>
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef}/>
        </div>

        {/* Input */}
        <div className="border-t border-border p-4">
          <p className="text-xs text-muted-foreground text-center mb-2">
            Answers grounded in the {productName} reviews
          </p>
          <div className="flex gap-2">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendMessage(input)}
              placeholder="Ask anything about this product's reviews..."
              className="flex-1 bg-card border border-border rounded-xl px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || loading}
              className="w-10 h-10 rounded-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center transition-colors"
            >
              <Send className="w-4 h-4 text-white"/>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
