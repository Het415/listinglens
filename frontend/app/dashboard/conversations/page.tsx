'use client'

import Link from 'next/link'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ArrowLeft, Sparkles, TrendingDown, TrendingUp } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from 'recharts'

import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { ScoreCard } from '@/components/dashboard/score-card'
import { DemoModeBanner } from '@/components/dashboard/demo-mode-banner'
import { DEMO_ASIN } from '@/lib/demo-config'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')

type Topic = { topic_id: number; label: string; keywords: string[]; size: number; share: number }
type SampleConvo = {
  conversation_id: string
  channel?: string
  intent?: string
  intent_seed?: string
  theme_seed?: string
  resolved?: boolean
  escalated?: boolean
  n_turns?: number
  sentiment_start?: number
  sentiment_end?: number
  sentiment_delta?: number
  sentiment_trajectory?: number[]
}
type ConversationAnalytics = {
  asin: string
  product_name?: string
  n_conversations: number
  intent_distribution: Record<string, number>
  resolution_rate: number
  escalation_rate: number
  avg_turns: number
  avg_sentiment_delta: number
  avg_sentiment_trajectory: { start: number; middle: number; end: number }
  intent_ood_accuracy: number
  topics: Topic[]
  sample_conversations: SampleConvo[]
}

type IntentResult = { category: string | null; intent: string | null; confidence: number; source: string }

function pct(n: number | undefined) {
  return `${Math.round((n ?? 0) * 100)}`
}

function ConversationsInner() {
  const searchParams = useSearchParams()
  const asinParam = searchParams.get('asin')
  const isDemo = !asinParam
  const asin = asinParam || DEMO_ASIN

  const [mounted, setMounted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<ConversationAnalytics | null>(null)

  useEffect(() => setMounted(true), [])

  useEffect(() => {
    if (!mounted) return
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError(null)
      setData(null)
      try {
        const res = await fetch(`${API_URL}/conversations/${asin}`)
        if (!res.ok) throw new Error(`No conversation analytics for ${asin} (${res.status})`)
        const json = (await res.json()) as ConversationAnalytics
        if (!cancelled) setData(json)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [asin, mounted])

  const topIntent = useMemo(() => {
    if (!data?.intent_distribution) return '—'
    const entries = Object.entries(data.intent_distribution)
    return entries.length ? entries[0][0] : '—'
  }, [data])

  const intentRows = useMemo(
    () =>
      data
        ? Object.entries(data.intent_distribution).map(([intent, count]) => ({ intent, count }))
        : [],
    [data],
  )

  const trajectoryRows = useMemo(() => {
    if (!data) return []
    const t = data.avg_sentiment_trajectory
    return [
      { stage: 'Start', sentiment: t.start },
      { stage: 'Middle', sentiment: t.middle },
      { stage: 'End', sentiment: t.end },
    ]
  }, [data])

  if (!mounted) return null

  return (
    <div className="min-h-screen space-y-6 bg-background p-4 text-foreground md:p-6">
      <div className="flex items-center gap-4">
        <Link
          href={asinParam ? `/dashboard?asin=${encodeURIComponent(asinParam)}` : '/dashboard'}
          className="text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-medium text-foreground">Conversation Analytics</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Support-transcript intent, sentiment trajectory &amp; topics — {`ASIN ${asin}`}
          </p>
        </div>
      </div>

      {isDemo && <DemoModeBanner productName={undefined} />}

      {/* Live classifier is always available, even without precomputed analytics */}
      <LiveClassifier productName={data?.product_name} />

      {error && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-800 dark:text-amber-200">
          {error}. Conversation analytics are precomputed per product — run{' '}
          <span className="font-mono text-xs">scripts.precompute_conversations</span> for this ASIN.
        </div>
      )}

      {loading && !error && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-32 animate-pulse rounded-xl border border-border bg-card" />
          ))}
        </div>
      )}

      {!loading && data && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <ScoreCard title="Resolution Rate" value={Number(pct(data.resolution_rate))} suffix="%"
              color="teal" progress={Number(pct(data.resolution_rate))} delay={1} />
            <ScoreCard title="Escalation Rate" value={Number(pct(data.escalation_rate))} suffix="%"
              color="red" progress={Number(pct(data.escalation_rate))} delay={2} />
            <ScoreCard title="Avg Turns / Convo" value={data.avg_turns} color="blue" delay={3} />
            <ScoreCard title="Conversations" value={data.n_conversations} color="default"
              subtext={`Top intent: ${topIntent}`} delay={4} />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Intent distribution */}
            <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
              <h2 className="mb-1 text-sm font-medium text-foreground">Intent Distribution</h2>
              <p className="mb-4 text-xs text-muted-foreground">
                Why customers contacted support (trained classifier + LLM fallback).
              </p>
              <ChartContainer id="intent-dist" config={{ count: { label: 'Conversations', color: 'var(--chart-1)' } }}
                className="h-[240px] w-full aspect-auto">
                <BarChart data={intentRows} layout="vertical" margin={{ left: 24, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
                  <YAxis dataKey="intent" type="category" width={120} tickLine={false} axisLine={false}
                    tick={{ fontSize: 11 }} />
                  <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="count" fill="var(--chart-1)" radius={[0, 6, 6, 0]} barSize={18} />
                </BarChart>
              </ChartContainer>
            </section>

            {/* Sentiment trajectory */}
            <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
              <h2 className="mb-1 flex items-center gap-2 text-sm font-medium text-foreground">
                Average Sentiment Trajectory
                {data.avg_sentiment_delta >= 0 ? (
                  <TrendingUp className="h-4 w-4 text-accent-teal" />
                ) : (
                  <TrendingDown className="h-4 w-4 text-accent-red" />
                )}
              </h2>
              <p className="mb-4 text-xs text-muted-foreground">
                Customer sentiment across the interaction (−1 to +1). Recovery = good service.
              </p>
              <ChartContainer id="sentiment-traj" config={{ sentiment: { label: 'Avg compound', color: 'var(--chart-2)' } }}
                className="h-[240px] w-full aspect-auto">
                <LineChart data={trajectoryRows} margin={{ left: 8, right: 16, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="stage" tickLine={false} axisLine={false} />
                  <YAxis domain={[-1, 1]} tickLine={false} axisLine={false} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Line type="monotone" dataKey="sentiment" stroke="var(--chart-2)" strokeWidth={2.5}
                    dot={{ r: 4 }} isAnimationActive />
                </LineChart>
              </ChartContainer>
            </section>
          </div>

          {/* Topics */}
          <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
            <h2 className="mb-1 text-sm font-medium text-foreground">Discussion Topics</h2>
            <p className="mb-4 text-xs text-muted-foreground">
              Embeddings-based topic modeling (MiniLM → KMeans → c-TF-IDF) over customer issues.
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.topics.map((t) => (
                <div key={t.topic_id} className="rounded-xl border border-border p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-sm font-medium text-foreground">{t.label}</span>
                    <span className="rounded border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      {Math.round(t.share * 100)}%
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {t.keywords.slice(0, 6).map((k, i) => (
                      <span key={i} className="rounded border border-border bg-background px-2 py-0.5 text-xs text-muted-foreground">
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Sample transcripts */}
          <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
            <h2 className="mb-4 text-sm font-medium text-foreground">Sample Conversations</h2>
            <div className="space-y-3">
              {data.sample_conversations.map((c) => (
                <div key={c.conversation_id} className="rounded-xl border border-border p-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-md bg-accent-blue/15 px-2 py-0.5 font-medium text-accent-blue">
                      {c.intent}
                    </span>
                    <span className="text-muted-foreground">{c.channel}</span>
                    <span className="text-muted-foreground">· {c.n_turns} turns</span>
                    {c.resolved ? (
                      <span className="text-accent-teal">· resolved</span>
                    ) : (
                      <span className="text-accent-amber">· unresolved</span>
                    )}
                    {c.escalated && <span className="text-accent-red">· escalated</span>}
                    <span className="ml-auto font-mono text-muted-foreground">
                      sentiment {c.sentiment_start?.toFixed(2)} → {c.sentiment_end?.toFixed(2)}
                    </span>
                  </div>
                  {c.theme_seed && (
                    <div className="mt-2 text-xs text-muted-foreground">Issue theme: {c.theme_seed}</div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}

function exampleFor(productName?: string) {
  const p = productName?.trim() || 'order'
  return `I want to return my ${p} and get a refund`
}

function LiveClassifier({ productName }: { productName?: string }) {
  const [text, setText] = useState(exampleFor(productName))
  const [result, setResult] = useState<IntentResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // Refresh the seeded example when the product changes — unless the user has
  // typed their own message (then we never clobber their input).
  const editedRef = useRef(false)
  useEffect(() => {
    if (!editedRef.current) setText(exampleFor(productName))
  }, [productName])

  const classify = async () => {
    setBusy(true)
    setErr(null)
    setResult(null)
    try {
      const res = await fetch(`${API_URL}/intent/classify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!res.ok) throw new Error(`Classifier error (${res.status})`)
      setResult((await res.json()) as IntentResult)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-medium text-foreground">
        <Sparkles className="h-4 w-4 text-accent-blue" /> Try the Intent Classifier
      </h2>
      <p className="mb-3 text-xs text-muted-foreground">
        Type a customer message. The trained model classifies it; low-confidence cases fall back to the LLM.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={text}
          onChange={(e) => {
            editedRef.current = true
            setText(e.target.value)
          }}
          onKeyDown={(e) => e.key === 'Enter' && classify()}
          placeholder="e.g. I never received my package"
          className="h-11 flex-1 rounded-lg border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none"
        />
        <button
          type="button"
          onClick={classify}
          disabled={busy || !text.trim()}
          className="h-11 rounded-lg bg-accent-blue px-5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {busy ? 'Classifying…' : 'Classify'}
        </button>
      </div>
      {err && <div className="mt-3 text-sm text-accent-red">{err}</div>}
      {result && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="rounded-md bg-accent-blue/15 px-3 py-1.5 text-sm font-medium text-accent-blue">
            {result.intent ?? 'Unknown'}
          </span>
          <span className="text-sm text-muted-foreground">
            confidence <span className="font-mono text-foreground">{(result.confidence * 100).toFixed(1)}%</span>
          </span>
          <span className={`rounded-md px-2 py-1 text-xs font-medium ${
            result.source === 'llm'
              ? 'bg-accent-amber/15 text-accent-amber'
              : 'bg-accent-teal/15 text-accent-teal'
          }`}>
            via {result.source === 'llm' ? 'LLM fallback' : 'trained model'}
          </span>
        </div>
      )}
    </section>
  )
}

export default function ConversationsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Loading…</div>}>
      <ConversationsInner />
    </Suspense>
  )
}
