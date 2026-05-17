import { Suspense } from 'react'
import { Sidebar, MobileNav } from '@/components/sidebar'
import { DashboardExportProvider } from '../dashboard/dashboard-export-context'
import { TopBarWithExport } from '../dashboard/top-bar-with-export'

// Mirrors app/chat/layout.tsx so the Copilot page sits inside the same
// sidebar + topbar shell as the rest of the app (instead of taking over
// the whole viewport like a top-level route).
export default function AgentLayout({ children }: { children: React.ReactNode }) {
  return (
    <DashboardExportProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar />
        <div className="flex-1 flex flex-col pb-16 md:pb-0">
          <Suspense fallback={<div className="h-[60px] bg-background-secondary border-b border-border" />}>
            <TopBarWithExport />
          </Suspense>
          <main className="flex-1 overflow-auto">{children}</main>
        </div>
        <MobileNav />
      </div>
    </DashboardExportProvider>
  )
}
