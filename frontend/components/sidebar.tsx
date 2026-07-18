'use client'

import { Suspense } from 'react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { Logo } from './logo'
import {
  LayoutDashboard,
  MessageSquareText,
  GitCompare,
  Sparkles,
  MessagesSquare,
  FileText,
} from 'lucide-react'

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/dashboard/reviews', label: 'Review Analysis', icon: MessageSquareText },
  { href: '/dashboard/conversations', label: 'Conversations', icon: MessagesSquare },
  { href: '/dashboard/compare', label: 'Competitor Compare', icon: GitCompare },
  { href: '/dashboard/brief', label: 'Executive Brief', icon: FileText },
  { href: '/assistant', label: 'AI Assistant', icon: Sparkles },
]

function useAsinHrefs() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const currentAsin = searchParams.get('asin')
  return { pathname, currentAsin }
}

// Carry the selected ASIN across navigation for every ASIN-scoped route.
function resolveHref(itemHref: string, currentAsin: string | null) {
  if (!currentAsin) return itemHref
  if (itemHref === '/dashboard') return itemHref // dashboard root reads its own default
  return `${itemHref}?asin=${encodeURIComponent(currentAsin)}`
}

// useSearchParams() forces a Suspense boundary or the whole page bails out of
// static prerendering at build time. The boundary lives here, inside the shared
// component, so every layout that renders <Sidebar /> is covered automatically.
export function Sidebar() {
  return (
    <Suspense fallback={<div className="hidden md:block w-[220px] border-r border-border-subtle" />}>
      <SidebarInner />
    </Suspense>
  )
}

function SidebarInner() {
  const { pathname, currentAsin } = useAsinHrefs()

  return (
    <aside className="hidden md:flex w-[220px] flex-col bg-background border-r border-border-subtle h-screen sticky top-0">
      <div className="p-4 border-b border-border-subtle">
        <Link href="/">
          <Logo size="small" />
        </Link>
      </div>

      <nav className="flex-1 py-4">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const href = resolveHref(item.href, currentAsin)
            const isActive =
              pathname === item.href ||
              (item.href === '/dashboard' &&
                pathname.startsWith('/dashboard') &&
                pathname !== '/dashboard/reviews' &&
                pathname !== '/dashboard/conversations' &&
                pathname !== '/dashboard/compare' &&
                pathname !== '/dashboard/brief')
            const Icon = item.icon

            return (
              <li key={item.href}>
                <Link
                  href={href}
                  className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors relative ${
                    isActive
                      ? 'text-text-primary bg-background-card'
                      : 'text-text-secondary hover:text-text-primary hover:bg-background-secondary'
                  }`}
                >
                  {isActive && (
                    <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-accent-blue animate-slide-in-left rounded-r" />
                  )}
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>
    </aside>
  )
}

export function MobileNav() {
  return (
    <Suspense fallback={null}>
      <MobileNavInner />
    </Suspense>
  )
}

function MobileNavInner() {
  const { pathname, currentAsin } = useAsinHrefs()

  const mobileItems = navItems.slice(0, 5)

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-background-secondary border-t border-border-subtle z-50">
      <ul className="flex justify-around py-2">
        {mobileItems.map((item) => {
          const href = resolveHref(item.href, currentAsin)
          const isActive =
            pathname === item.href ||
            (item.href === '/dashboard' && pathname.startsWith('/dashboard'))
          const Icon = item.icon

          return (
            <li key={item.href}>
              <Link
                href={href}
                className={`flex flex-col items-center gap-1 px-3 py-2 text-xs transition-colors ${
                  isActive ? 'text-accent-blue' : 'text-text-secondary'
                }`}
              >
                <Icon className="w-5 h-5" />
                <span className="truncate max-w-[60px]">{item.label.split(' ')[0]}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
