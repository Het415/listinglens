'use client'
import { useState } from 'react'
import { Sparkles, Star, Copy, Check, ChevronDown } from 'lucide-react'
import type { ChatMessage } from './types'
import { ratingStyle, sentimentBadge, chatAnswerToText } from './style-helpers'

export function AssistantMessage({ msg }: { msg: ChatMessage }) {
  const [copied, setCopied] = useState(false)
  const [allOpen, setAllOpen] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(
        chatAnswerToText(msg.content || '', msg.sources),
      )
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
        <details
          className="mt-3 group"
          open={allOpen}
          onToggle={(e) => setAllOpen((e.target as HTMLDetailsElement).open)}
        >
          <summary className="cursor-pointer text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground transition list-none flex items-center gap-1.5">
            <ChevronDown className="w-3 h-3 transition group-open:rotate-180" />
            <span>Sources ({msg.sources.length})</span>
          </summary>
          <div className="mt-2 space-y-1.5">
            {msg.sources.map((s, i) => {
              const rstyle = ratingStyle(s.rating)
              const sbadge = sentimentBadge(s.sentiment)
              return (
                <div key={i} className={`rounded-lg border p-2.5 ${rstyle.ring}`}>
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
