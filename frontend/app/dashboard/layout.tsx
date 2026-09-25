import { Suspense } from 'react'
import { Sidebar, MobileNav } from '@/components/sidebar'
import { DashboardExportProvider } from './dashboard-export-context'
import { TopBarWithExport } from './top-bar-with-export'

// min-w-0 on the content column. A flex item defaults to min-width: auto, so it
// can never be narrower than its widest child. On a phone, Review Analysis's
// chart and reviews table widened the column to 589px in a 375px window, and
// the top bar went with it, pushing Ask AI off-screen. The chart's
// ResponsiveContainer then measured that too-wide column and stayed wide, so
// it never gave the space back. With min-w-0 the column is the viewport minus
// the sidebar; anything genuinely wider (the table) scrolls inside its own box.
// The chat, agent and assistant layouts carry the same fix.
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <DashboardExportProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar />
        <div className="flex-1 min-w-0 flex flex-col pb-16 md:pb-0">
          <Suspense fallback={<div className="h-[60px] bg-background-secondary border-b border-border" />}>
            <TopBarWithExport />
          </Suspense>
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
        <MobileNav />
      </div>
    </DashboardExportProvider>
  )
}
