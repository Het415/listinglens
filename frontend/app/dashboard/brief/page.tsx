'use client'

import Link from 'next/link'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ArrowLeft, AlertTriangle, CheckCircle2, FileText } from 'lucide-react'

import { ScoreCard } from '@/components/dashboard/score-card'
import { DemoModeBanner } from '@/components/dashboard/demo-mode-banner'
import { DEMO_ASIN } from '@/lib/demo-config'
import { exportBriefToPDF, type BriefResponse } from '@/lib/exportBrief'
import { useDashboardExport } from '../dashboard-export-context'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const PRIORITY_STYLE: Record<string, string> = {
  high: 'bg-accent-red/15 text-accent-red',
  medium: 'bg-accent-amber/15 text-accent-amber',
  low: 'bg-accent-teal/15 text-accent-teal',
}

function BriefInner() {
  const searchParams = useSearchParams()
  const asinParam = searchParams.get('asin')
  const isDemo = !asinParam
  const asin = asinParam || DEMO_ASIN

  const [mounted, setMounted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<BriefResponse | null>(null)

  const { setOnExport, setIsExporting } = useDashboardExport()

  useEffect(() => setMounted(true), [])

  useEffect(() => {
    if (!mounted) return
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError(null)
      setData(null)
      try {
        const res = await fetch(`${API_URL}/brief/${asin}`)
        if (!res.ok) throw new Error(`Could not generate brief for ${asin} (${res.status})`)
        const json = (await res.json()) as BriefResponse
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

  // Register the PDF exporter with the shared top-bar Export button.
  useEffect(() => {
    if (!data) {
      setOnExport(null)
      return
    }
    setOnExport(async () => {
      setIsExporting(true)
      try {
        await exportBriefToPDF(data)
      } finally {
        setIsExporting(false)
      }
    })
    return () => setOnExport(null)
  }, [data, setOnExport, setIsExporting])

  if (!mounted) return null

  const m = data?.metrics
  const brief = data?.brief

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
          <h1 className="flex items-center gap-2 text-2xl font-medium text-foreground">
            <FileText className="h-5 w-5 text-accent-blue" /> Executive Brief
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {data?.product_name || `ASIN ${asin}`} — AI-synthesized leadership summary
          </p>
        </div>
      </div>

      {isDemo && <DemoModeBanner productName={data?.product_name} />}

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading && !error && (
        <div className="space-y-4">
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-32 animate-pulse rounded-xl border border-border bg-card" />
            ))}
          </div>
          <p className="text-center text-xs text-muted-foreground">Synthesizing brief with the LLM…</p>
        </div>
      )}

      {!loading && brief && m && (
        <>
          {/* Headline */}
          <section className="rounded-xl border border-border bg-gradient-to-br from-accent-blue/10 to-transparent p-6">
            <h2 className="text-lg font-medium text-foreground">{brief.headline}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{brief.situation}</p>
          </section>

          {/* KPI row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <ScoreCard title="Return Risk" value={Math.round(m.return_risk?.risk_pct ?? 0)} suffix="%"
              color="red" badge={m.return_risk?.risk_label} delay={1} />
            <ScoreCard title="Negative Reviews" value={Math.round(m.pct_negative ?? 0)} suffix="%"
              color="amber" progress={Math.round(m.pct_negative ?? 0)} delay={2} />
            <ScoreCard title="Avg Rating" value={m.avg_rating ?? 0} stars={m.avg_rating ?? 0}
              color="teal" delay={3} />
            <ScoreCard
              title="Resolution Rate"
              value={Math.round((m.conversations?.resolution_rate ?? 0) * 100)}
              suffix="%"
              color="blue"
              subtext={m.conversations ? undefined : 'No conversation data'}
              delay={4}
            />
          </div>

          {/* Key findings */}
          <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
            <h2 className="mb-4 text-sm font-medium text-foreground">Key Findings</h2>
            <div className="space-y-3">
              {brief.key_findings.map((f, i) => (
                <div key={i} className="flex gap-3">
                  <div className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-accent-blue" />
                  <div>
                    <div className="text-sm font-medium text-foreground">{f.metric}</div>
                    <div className="text-sm text-muted-foreground">{f.insight}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Risks */}
            <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
              <h2 className="mb-4 flex items-center gap-2 text-sm font-medium text-foreground">
                <AlertTriangle className="h-4 w-4 text-accent-amber" /> Top Risks
              </h2>
              <ul className="space-y-2">
                {brief.top_risks.map((r, i) => (
                  <li key={i} className="flex gap-2 text-sm text-muted-foreground">
                    <span className="text-accent-amber">•</span> {r}
                  </li>
                ))}
              </ul>
            </section>

            {/* Actions */}
            <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
              <h2 className="mb-4 flex items-center gap-2 text-sm font-medium text-foreground">
                <CheckCircle2 className="h-4 w-4 text-accent-teal" /> Recommended Actions
              </h2>
              <div className="space-y-3">
                {brief.recommended_actions.map((a, i) => (
                  <div key={i} className="rounded-lg border border-border p-3">
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-sm font-medium text-foreground">{a.action}</span>
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${PRIORITY_STYLE[a.priority] || 'bg-muted text-muted-foreground'}`}>
                        {a.priority}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{a.rationale}</div>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <p className="text-center text-xs text-muted-foreground">
            Brief confidence: {Math.round((brief.confidence ?? 0) * 100)}% · Use the Export Report button to download as PDF.
          </p>
        </>
      )}
    </div>
  )
}

export default function BriefPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Loading…</div>}>
      <BriefInner />
    </Suspense>
  )
}
