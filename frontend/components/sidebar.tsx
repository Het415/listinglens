'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Logo } from './logo'
import { 
  LayoutDashboard, 
  MessageSquareText, 
  Eye, 
  GitCompare, 
  Bot, 
  Settings,
  Clock
} from 'lucide-react'

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/dashboard/reviews', label: 'Review Analysis', icon: MessageSquareText },
  { href: '/dashboard/visual', label: 'Visual Scoring', icon: Eye },
  { href: '/dashboard/compare', label: 'Competitor Compare', icon: GitCompare },
  { href: '/chat', label: 'Ask AI', icon: Bot },
  { href: '/dashboard/settings', label: 'Settings', icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()

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
            const isActive = pathname === item.href || 
              (item.href === '/dashboard' && pathname.startsWith('/dashboard') && pathname !== '/dashboard/reviews' && pathname !== '/dashboard/visual' && pathname !== '/dashboard/compare' && pathname !== '/dashboard/settings')
            const Icon = item.icon
            
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
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
      
      <div className="p-4 border-t border-border-subtle">
        <div className="bg-background-card rounded-lg p-3 text-xs text-text-secondary">
          <div className="flex items-center gap-2 mb-1">
            <Clock className="w-3 h-3" />
            <span>Analyzed 4 min ago</span>
          </div>
          <div className="text-text-muted">
            247 reviews · 6 images processed
          </div>
        </div>
      </div>
    </aside>
  )
}

export function MobileNav() {
  const pathname = usePathname()

  const mobileItems = navItems.slice(0, 5)

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-background-secondary border-t border-border-subtle z-50">
      <ul className="flex justify-around py-2">
        {mobileItems.map((item) => {
          const isActive = pathname === item.href || 
            (item.href === '/dashboard' && pathname.startsWith('/dashboard'))
          const Icon = item.icon
          
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={`flex flex-col items-center gap-1 px-3 py-2 text-xs transition-colors ${
                  isActive 
                    ? 'text-accent-blue' 
                    : 'text-text-secondary'
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
