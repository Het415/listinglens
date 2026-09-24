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
  ImageIcon,
  FolderOpen,
} from 'lucide-react'

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  // Second, not last. It is the only feature that works on the seller's own
  // product rather than on one of the twelve demo ASINs, and it needs neither
  // an ASIN nor the review pipeline — so it belongs near the top rather than
  // buried behind a mode toggle on another page, which is where it started.
  { href: '/dashboard/images', label: 'Image Audit', icon: ImageIcon },
  { href: '/dashboard/reviews', label: 'Review Analysis', icon: MessageSquareText },
  { href: '/dashboard/conversations', label: 'Conversations', icon: MessagesSquare },
  { href: '/dashboard/compare', label: 'Competitor Compare', icon: GitCompare },
  { href: '/dashboard/brief', label: 'Executive Brief', icon: FileText },
  { href: '/assistant', label: 'AI Assistant', icon: Sparkles },
  { href: '/dashboard/reports', label: 'My Reports', icon: FolderOpen },
]

function useAsinHrefs() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const currentAsin = searchParams.get('asin')
  return { pathname, currentAsin }
}

/** Which nav item the current path belongs to.
 *
 * `/dashboard` is the section root, so it stays lit for any `/dashboard/*` page
 * that has no sidebar entry of its own — but never for one that does, or two
 * items highlight at once. Derived from `navItems` rather than a hardcoded
 * list: the previous version enumerated four sibling paths inline and would
 * have silently double-highlighted the moment a fifth was added, which is
 * exactly what adding Image Audit does.
 */
function isNavActive(pathname: string, itemHref: string) {
  if (pathname === itemHref) return true
  return (
    itemHref === '/dashboard' &&
    pathname.startsWith('/dashboard') &&
    !navItems.some((i) => i.href !== '/dashboard' && pathname === i.href)
  )
}

// Carry the selected ASIN across navigation for every ASIN-scoped route.
function resolveHref(itemHref: string, currentAsin: string | null) {
  if (!currentAsin) return itemHref
  // `/dashboard` used to be excepted here, with the comment "dashboard root
  // reads its own default". It does — `app/dashboard/page.tsx` falls back to
  // DEMO_ASIN — which is precisely the bug: clicking Dashboard silently swapped
  // the user's product for the demo one.
  //
  // And the damage did not stop at that page. The URL is the only carrier of
  // product identity, so once the param is gone `currentAsin` is null, the
  // guard above returns bare hrefs for EVERY nav item, and the selection is
  // unrecoverable for the rest of the session short of browser Back. One
  // omitted query param was an absorbing state.
  //
  // Not a regression from a fix: the exception arrived in e5e0440e when an
  // allowlist was inverted into a denylist, and it preserved a hole dating to
  // f1cef6e57. The comment was a rationalisation of an omission.
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
            const isActive = isNavActive(pathname, item.href)
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

  // Six, not five. The slice used to cut the list at five, which excluded AI
  // Assistant; adding Image Audit at index 1 would have pushed Executive Brief
  // out too. Widening is additive — nothing that was reachable on a phone stops
  // being reachable — and a seller on a phone is the one holding the photos.
  // AI Assistant is still outside the slice; that predates this change.
  const mobileItems = navItems.slice(0, 6)

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-background-secondary border-t border-border-subtle z-50">
      <ul className="flex justify-around py-2">
        {mobileItems.map((item) => {
          const href = resolveHref(item.href, currentAsin)
          const isActive = isNavActive(pathname, item.href)
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
