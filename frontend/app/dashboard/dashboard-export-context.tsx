'use client'

import { createContext, useCallback, useContext, useRef, useState } from 'react'
import type { AnalyzeResponse } from '@/lib/exportReport'

type OnExport = (() => Promise<void>) | null

type DashboardExportContextValue = {
  analysis: AnalyzeResponse | null
  setAnalysis: (v: AnalyzeResponse | null) => void
  isExporting: boolean
  setIsExporting: (v: boolean) => void
  onExport: OnExport
  setOnExport: (v: OnExport) => void
}

const DashboardExportContext = createContext<
  DashboardExportContextValue | undefined
>(undefined)

export function DashboardExportProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null)
  const [isExporting, setIsExporting] = useState(false)

  // `onExport` is a function. Storing it in `useState` can cause React/TS
  // to interpret function values as "state updaters", leading to awkward typing.
  // Using a ref avoids that ambiguity.
  const onExportRef = useRef<OnExport>(null)
  const [canExport, setCanExport] = useState(false)

  const exportWrapper = useCallback(async () => {
    const fn = onExportRef.current
    if (!fn) return
    await fn()
  }, [])

  const onExport: OnExport = canExport ? exportWrapper : null

  const setOnExport = (v: OnExport) => {
    onExportRef.current = v
    setCanExport(Boolean(v))
  }

  return (
    <DashboardExportContext.Provider
      value={{
        analysis,
        setAnalysis,
        isExporting,
        setIsExporting,
        onExport,
        setOnExport,
      }}
    >
      {children}
    </DashboardExportContext.Provider>
  )
}

export function useDashboardExport() {
  const ctx = useContext(DashboardExportContext)
  if (!ctx) {
    throw new Error('useDashboardExport must be used within DashboardExportProvider')
  }
  return ctx
}

