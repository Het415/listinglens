'use client'

import Link from 'next/link'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ArrowLeft, FileText } from 'lucide-react'

import { BriefView } from '@/components/dashboard/brief-view'
import { SaveReportButton } from '@/components/auth/save-report-button'
import { DemoModeBanner } from '@/components/dashboard/demo-mode-banner'
import { DEMO_ASIN } from '@/lib/demo-config'
import { isAbortError } from '@/lib/abort'
import { exportBriefToPDF, type BriefResponse } from '@/lib/exportBrief'
import { useDashboardExport } from '../dashboard-export-context'
import { DashboardLoading, RouteFallback, SkeletonGrid, SkeletonPanel } from '@/components/dashboard/loading'
import { apiUrl } from '@/lib/api'

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
    // Drop the in-flight request when the ASIN changes — `cancelled` alone
    // would ignore the response but leave the connection open.
    const controller = new AbortController()
    const run = async () => {
      setLoading(true)
      setError(null)
      setData(null)
      try {
        const res = await fetch(apiUrl(`/brief/${asin}`), { signal: controller.signal })
        if (!res.ok) throw new Error(`Could not generate brief for ${asin} (${res.status})`)
        const json = (await res.json()) as BriefResponse
        if (!cancelled) setData(json)
      } catch (e) {
        // A deliberate abort isn't a failure — stay silent and let the newer
        // load own the UI.
        if (isAbortError(e)) return
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
      controller.abort()
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

  return (
    <div className="min-h-screen space-y-6 bg-background p-4 text-foreground md:p-6">
      <div className="flex items-center gap-4">
        <Link
          href={asinParam ? `/dashboard?asin=${encodeURIComponent(asinParam)}` : '/dashboard'}
          className="text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="flex-1">
          <h1 className="flex items-center gap-2 text-2xl font-medium text-foreground">
            <FileText className="h-5 w-5 text-accent-blue" /> Executive Brief
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {data?.product_name || `ASIN ${asin}`} — AI-synthesized leadership summary
          </p>
        </div>
        {data?.brief && (
          <SaveReportButton
            report={{
              kind: 'brief',
              asin,
              title: `${data.product_name || asin}: executive brief`,
              data,
            }}
          />
        )}
      </div>

      {isDemo && <DemoModeBanner productName={data?.product_name} />}

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading && !error && (
        <DashboardLoading
          note="Synthesizing brief with the LLM"
          slowNote="The brief is generated fresh on a cache miss, which takes ~15s. Reloads are instant."
        >
          {/* Headline block, then the KPI row — same grid as the real one. */}
          <SkeletonPanel className="h-24" />
          <SkeletonGrid count={4} />
        </DashboardLoading>
      )}

      {!loading && data?.brief && data?.metrics && (
        <BriefView data={data} footnote="Use the Export Report button to download as PDF." />
      )}
    </div>
  )
}

export default function BriefPage() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <BriefInner />
    </Suspense>
  )
}
