'use client'

import { Suspense, useMemo, useState, useEffect, useRef } from 'react'
import { Star } from 'lucide-react'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const SUPPORTED_PRODUCTS = [
  { name: 'TOZO T10 Earbuds', asin: 'B08XPWDSWW' },
  { name: 'Fire Stick 4K', asin: 'B07GZFM1ZM' },
  { name: 'Fire TV Stick', asin: 'B075X8471B' },
  { name: 'Echo Dot 2nd Gen', asin: 'B01K8B8YA8' },
  { name: 'Echo Dot 3rd Gen', asin: 'B07H65KP63' },
  { name: 'Fire TV Stick HD', asin: 'B0791TX5P5' },
  { name: 'Fire Tablet 7 inch', asin: 'B010BWYDYA' },
] as const

type AnalyzeResponse = {
  asin: string
  product_name?: string
  summary?: {
    avg_rating?: number
    pct_negative?: number
    pct_positive?: number
    top_topics?: Array<{ keywords?: string[]; label?: string }>
  }
  features?: {
    avg_compound_score?: number
  }
  risk?: {
    risk_score?: number
    risk_pct?: number
    risk_label?: string
  }
}

type CompareCard = {
  asin: string
  name: string
  overallScore: number
  returnRiskPct: number
  returnRiskLabel: string
  avgRating: number
  pctNegative: number
  pctPositive: number
  topKeywords: string[]
  compoundScore: number
}

function normalizeInputToAsin(value: string): string | null {
  const input = value.trim()
  if (!input) return null
  if (/^[A-Z0-9]{10}$/i.test(input)) return input.toUpperCase()
  const m = input.match(/\/dp\/([A-Z0-9]{10})/i)
  if (m) return m[1].toUpperCase()
  const m2 = input.match(/([A-Z0-9]{10})/i)
  if (m2) return m2[1].toUpperCase()
  return null
}

function toCard(data: AnalyzeResponse): CompareCard {
  const riskScore = data.risk?.risk_score ?? 0
  const returnRiskPct = data.risk?.risk_pct ?? Math.round(riskScore * 100)
  const topKeywords = (data.summary?.top_topics || [])
    .flatMap((t) => (t.keywords && t.keywords.length ? t.keywords : t.label ? [t.label] : []))
    .filter(Boolean)
    .slice(0, 3)

  return {
    asin: data.asin,
    name: data.product_name || data.asin,
    overallScore: Math.round((1 - riskScore) * 100),
    returnRiskPct,
    returnRiskLabel: (data.risk?.risk_label || 'UNKNOWN').toUpperCase(),
    avgRating: Number((data.summary?.avg_rating ?? 0).toFixed(1)),
    pctNegative: data.summary?.pct_negative ?? 0,
    pctPositive: data.summary?.pct_positive ?? 0,
    topKeywords,
    compoundScore: Number((data.features?.avg_compound_score ?? 0).toFixed(3)),
  }
}

function riskColor(label: string): string {
  if (label === 'HIGH') return 'text-accent-red'
  if (label === 'MEDIUM') return 'text-accent-amber'
  if (label === 'LOW') return 'text-accent-green'
  return 'text-text-secondary'
}

function ProductSlot({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  return (
    <div className="relative" ref={wrapRef}>
      <label className="block text-xs text-text-secondary mb-2">{label}</label>
      <input
        value={value}
        onFocus={() => setOpen(value.trim() === '')}
        onChange={(e) => {
          const next = e.target.value
          onChange(next)
          setOpen(next.trim() === '')
        }}
        placeholder="ASIN or Amazon URL"
        className="w-full h-11 bg-[#16161F] border border-[#2A2A3A] rounded-lg px-3 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
      />
      {open && (
        <div className="absolute left-0 right-0 mt-2 rounded-lg border border-[#2A2A3A] bg-[#16161F] z-50 max-h-56 overflow-auto">
          {SUPPORTED_PRODUCTS.map((p) => (
            <button
              key={p.asin}
              type="button"
              onClick={() => {
                onChange(p.asin)
                setOpen(false)
              }}
              className="w-full text-left px-3 py-2 hover:bg-[#1A1A26] border-b border-[#2A2A3A] last:border-b-0"
            >
              <div className="text-sm text-text-primary">{p.name}</div>
              <div className="text-xs font-mono text-text-muted">{p.asin}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ComparePageContent() {
  const [slot1, setSlot1] = useState('')
  const [slot2, setSlot2] = useState('')
  const [slot3, setSlot3] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cards, setCards] = useState<CompareCard[]>([])

  const selectedAsins = useMemo(() => {
    const raw = [slot1, slot2, slot3]
      .map(normalizeInputToAsin)
      .filter((v): v is string => Boolean(v))
    return Array.from(new Set(raw))
  }, [slot1, slot2, slot3])

  const canCompare = selectedAsins.length >= 2

  const winnerAsin = useMemo(() => {
    if (!cards.length) return null
    return [...cards].sort((a, b) => a.returnRiskPct - b.returnRiskPct)[0]?.asin || null
  }, [cards])

  const insight = useMemo(() => {
    if (cards.length < 2) return ''
    const byRisk = [...cards].sort((a, b) => a.returnRiskPct - b.returnRiskPct)
    const byPositive = [...cards].sort((a, b) => b.pctPositive - a.pctPositive)
    const bestRisk = byRisk[0]
    const bestPos = byPositive[0]
    const extra =
      bestRisk.asin === bestPos.asin
        ? `${bestRisk.name} also leads in positive sentiment at ${bestRisk.pctPositive}%.`
        : `${bestPos.name} has stronger positive sentiment at ${bestPos.pctPositive}%.`
    return `${bestRisk.name} has the lowest return risk at ${bestRisk.returnRiskPct}% and the strongest listing score at ${bestRisk.overallScore}/100. ${extra} Consider using top-performing topic keywords and listing structure from this winner.`
  }, [cards])

  const handleCompare = async () => {
    if (!canCompare) return
    setLoading(true)
    setError(null)
    try {
      const results = await Promise.all(
        selectedAsins.map(async (asin) => {
          const res = await fetch(`${API_URL}/analyze/${asin}`)
          if (!res.ok) {
            throw new Error(`ASIN ${asin} not found in cached results`)
          }
          return (await res.json()) as AnalyzeResponse
        }),
      )
      setCards(results.map(toCard))
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Comparison failed'
      setError(message)
      setCards([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-4 md:p-6 space-y-6 bg-[#0A0A0F] min-h-screen">
      <div>
        <h1 className="text-2xl font-medium text-text-primary">Competitor Compare</h1>
        <p className="text-sm text-text-secondary mt-1">Compare 2-3 products side by side using cached analysis.</p>
      </div>

      <div className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-4 md:p-5">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <ProductSlot label="Add Product 1" value={slot1} onChange={setSlot1} />
          <ProductSlot label="Add Product 2" value={slot2} onChange={setSlot2} />
          <ProductSlot label="Add Product 3 (optional)" value={slot3} onChange={setSlot3} />
        </div>
        <div className="mt-4 flex items-center justify-between">
          <div className="text-xs text-text-muted">Minimum 2 products required. Duplicate ASINs are ignored.</div>
          <button
            onClick={handleCompare}
            disabled={!canCompare || loading}
            className={`h-10 px-5 rounded-lg text-sm font-medium transition-colors ${
              canCompare && !loading
                ? 'bg-accent-blue text-white hover:bg-accent-blue/90'
                : 'bg-[#2A2A3A] text-text-muted cursor-not-allowed'
            }`}
          >
            {loading ? 'Comparing...' : 'Compare'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5 space-y-3 animate-pulse">
              <div className="h-5 w-2/3 bg-[#2A2A3A] rounded" />
              <div className="h-4 w-1/3 bg-[#2A2A3A] rounded" />
              <div className="h-3 w-full bg-[#2A2A3A] rounded" />
              <div className="h-3 w-5/6 bg-[#2A2A3A] rounded" />
              <div className="h-3 w-4/5 bg-[#2A2A3A] rounded" />
              <div className="h-3 w-2/3 bg-[#2A2A3A] rounded" />
            </div>
          ))}
        </div>
      )}

      {!loading && cards.length >= 2 && (
        <>
          <div className={`grid grid-cols-1 ${cards.length === 2 ? 'lg:grid-cols-2' : 'lg:grid-cols-3'} gap-4`}>
            {cards.map((c) => {
              const isWinner = c.asin === winnerAsin
              return (
                <div
                  key={c.asin}
                  className={`bg-[#16161F] rounded-xl p-5 border ${
                    isWinner ? 'border-accent-blue shadow-[0_0_0_1px_rgba(79,142,247,0.35),0_0_24px_rgba(79,142,247,0.2)]' : 'border-[#2A2A3A]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-medium text-text-primary leading-snug">{c.name}</h3>
                      <p className="text-xs font-mono text-text-muted mt-1">{c.asin}</p>
                    </div>
                    {isWinner && (
                      <span className="text-xs px-2 py-1 rounded bg-accent-blue/20 text-accent-blue border border-accent-blue/40">
                        Winner
                      </span>
                    )}
                  </div>

                  <div className="mt-4 space-y-2.5 text-sm">
                    <MetricRow label="Overall Listing Score" value={`${c.overallScore}/100`} />
                    <MetricRow
                      label="Return Risk"
                      value={`${c.returnRiskPct}%`}
                      suffix={<span className={`text-xs font-medium ${riskColor(c.returnRiskLabel)}`}>{c.returnRiskLabel}</span>}
                    />
                    <MetricRow
                      label="Average Star Rating"
                      value={
                        <span className="flex items-center gap-1">
                          {c.avgRating}
                          <Star className="w-3.5 h-3.5 text-accent-amber fill-current" />
                        </span>
                      }
                    />
                    <MetricRow label="% Negative Reviews" value={`${c.pctNegative}%`} />
                    <MetricRow label="% Positive Reviews" value={`${c.pctPositive}%`} />
                    <MetricRow label="Sentiment Compound" value={c.compoundScore} />
                    <MetricRow
                      label="Top 3 Topics"
                      value={
                        <span className="text-right">
                          {c.topKeywords.length ? c.topKeywords.join(' · ') : 'N/A'}
                        </span>
                      }
                    />
                  </div>
                </div>
              )
            })}
          </div>

          <div className="bg-[#16161F] border border-[#2A2A3A] rounded-xl p-5">
            <h4 className="text-sm font-medium text-text-primary mb-2">AI Insight</h4>
            <p className="text-sm text-text-secondary leading-relaxed">{insight}</p>
          </div>
        </>
      )}
    </div>
  )
}

function MetricRow({
  label,
  value,
  suffix,
}: {
  label: string
  value: React.ReactNode
  suffix?: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-text-secondary">{label}</span>
      <div className="flex items-center gap-2 text-text-primary font-medium text-right">
        <span>{value}</span>
        {suffix}
      </div>
    </div>
  )
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Loading...</div>}>
      <ComparePageContent />
    </Suspense>
  )
}
