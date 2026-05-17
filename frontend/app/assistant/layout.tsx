import { Suspense } from 'react'
import { Sidebar, MobileNav } from '@/components/sidebar'
import { DashboardExportProvider } from '../dashboard/dashboard-export-context'
import { TopBarWithExport } from '../dashboard/top-bar-with-export'

// Mirrors /agent/layout.tsx: h-screen + overflow-hidden so the page itself
// never scrolls. Overflow happens inside the messages container.
export default function AssistantLayout({ children }: { children: React.ReactNode }) {
  return (
    <DashboardExportProvider>
      <div className="flex h-screen bg-background overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col min-h-0 pb-16 md:pb-0">
          <Suspense fallback={<div className="h-[60px] bg-background-secondary border-b border-border" />}>
            <TopBarWithExport />
          </Suspense>
          <main className="flex-1 min-h-0 overflow-hidden">{children}</main>
        </div>
        <MobileNav />
      </div>
    </DashboardExportProvider>
  )
}
