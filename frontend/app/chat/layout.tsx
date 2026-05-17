import { Suspense } from 'react'
import { Sidebar, MobileNav } from '@/components/sidebar'
import { DashboardExportProvider } from '../dashboard/dashboard-export-context'
import { TopBarWithExport } from '../dashboard/top-bar-with-export'

// Same h-screen + overflow-hidden trick as app/agent/layout.tsx.
// The new /chat assistant cards now show all 5 source cards (vs 2 truncated
// lines before), which can stack tall enough to overflow viewport. With
// min-h-screen, the outer document grew past 100vh and scrolled the WHOLE
// page instead of the messages list. h-screen pins the wrapper to exactly
// viewport height so the overflow-y-auto on the messages list activates
// properly and only that list scrolls.
export default function ChatLayout({ children }: { children: React.ReactNode }) {
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

