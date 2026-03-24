import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

export default function VisualPage() {
  return (
    <div className="p-6">
      <div className="flex items-center gap-4 mb-6">
        <Link href="/dashboard" className="text-text-secondary hover:text-text-primary">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <h1 className="text-2xl font-medium text-text-primary">Visual Scoring</h1>
      </div>
      <div className="bg-background-card border border-border rounded-xl p-8 text-center">
        <p className="text-text-secondary">Visual quality scoring coming soon...</p>
        <p className="text-text-muted text-sm mt-2">This page will show CLIP-based image analysis and recommendations.</p>
      </div>
    </div>
  )
}
