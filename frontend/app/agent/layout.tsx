import { Suspense } from 'react'
import { Sidebar, MobileNav } from '@/components/sidebar'
import { DashboardExportProvider } from '../dashboard/dashboard-export-context'
import { TopBarWithExport } from '../dashboard/top-bar-with-export'

// Mirrors app/chat/layout.tsx so the Copilot page sits inside the same
// sidebar + topbar shell as the rest of the app — with one deliberate
// deviation: h-screen instead of min-h-screen.
//
// The /chat layout uses min-h-screen because its content (short chat
// bubbles) rarely exceeds viewport. /agent renders full Recommendation
// cards that often DO exceed viewport, and min-h-screen lets the outer
// document grow past 100vh — scrolling the whole page instead of the
// messages container. h-screen pins the wrapper to exactly 100vh so
// overflow happens INSIDE the messages list (where overflow-y-auto is
// actually wired up) and the page itself never scrolls.
export default function AgentLayout({ children }: { children: React.ReactNode }) {
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
