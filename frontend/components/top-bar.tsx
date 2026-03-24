'use client'

import Link from 'next/link'
import { Logo } from './logo'
import { Download, ChevronRight } from 'lucide-react'

interface TopBarProps {
  breadcrumb?: string[]
}

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'

export function TopBar() {
  const searchParams = useSearchParams()
  const asin = searchParams.get('asin') || 'B08XPWDSWW'
  const [productName, setProductName] = useState(asin)

  useEffect(() => {
    const cached = sessionStorage.getItem(`analysis_${asin}`)
    if (cached) {
      const data = JSON.parse(cached)
      setProductName(data.product_name || asin)
    }
  }, [asin])

  return (
    <header className="h-[60px] bg-background-secondary border-b border-border flex items-center justify-between px-4 md:px-6">
      <div className="md:hidden">
        <Link href="/">
          <Logo size="small" />
        </Link>
      </div>
      <nav className="hidden md:flex items-center gap-2 text-sm text-text-secondary">
        <span className="flex items-center gap-2">
          <ChevronRight className="w-4 h-4 text-text-muted" />
          <span className="text-text-primary">
            {productName}
          </span>
        </span>
      </nav>
      
      <div className="flex items-center gap-3">
        <button className="hidden md:flex items-center gap-2 px-4 py-2 text-sm border border-border rounded-lg text-text-secondary hover:border-border-hover hover:text-text-primary transition-colors">
          <Download className="w-4 h-4" />
          <span>Export Report</span>
        </button>

        <Link
          href="/chat"
          className="flex items-center gap-2 px-4 py-2 text-sm bg-accent-teal text-background font-medium rounded-lg hover:bg-accent-teal/90 transition-colors"
        >
          Ask AI
        </Link>

        <div className="w-8 h-8 rounded-full bg-background-card border border-border flex items-center justify-center">
          <span className="text-xs text-text-secondary">U</span>
        </div>
      </div>
    </header>
  )
}
