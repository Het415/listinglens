import { Suspense } from 'react'
import { Sidebar, MobileNav } from '@/components/sidebar'
import { TopBar } from '@/components/top-bar'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col pb-16 md:pb-0">
        <Suspense fallback={<div className="h-[60px] bg-background-secondary border-b border-border" />}>
          <TopBar />
        </Suspense>
        <main className="flex-1 overflow-auto">
          {children}
        </main>
      </div>
      <MobileNav />
    </div>
  )
}
