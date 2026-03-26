'use client'

import { TopBar } from '@/components/top-bar'
import { useDashboardExport } from './dashboard-export-context'

export function TopBarWithExport() {
  const { onExport, isExporting } = useDashboardExport()

  return <TopBar onExport={onExport} isExporting={isExporting} />
}

