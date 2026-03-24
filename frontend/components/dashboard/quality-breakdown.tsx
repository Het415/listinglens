'use client'

import { Check, X, AlertTriangle, ArrowRight } from 'lucide-react'

const qualityChecks = [
  { label: 'Title keyword coverage', status: 'good', value: '84%' },
  { label: 'Image count (only 3, need 7+)', status: 'critical', value: '43%' },
  { label: 'Primary image background', status: 'critical', value: 'white bg missing' },
  { label: 'Description length', status: 'warning', value: '67%' },
  { label: 'Bullet points structure', status: 'good', value: '91%' },
  { label: 'A+ Content present', status: 'warning', value: 'not detected' },
]

const recommendations = [
  'Add 4 more product images showing the headphone from different angles and in-use scenarios',
  'Revise product description to address battery expectations — set realistic 20hr claim prominently',
  'Respond to top 10 battery complaints publicly to show customer service quality',
]

export function QualityBreakdown() {
  return (
    <div className="space-y-4">
      <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-6">
        <h3 className="font-medium text-text-primary mb-4">Listing Quality Breakdown</h3>
        
        <div className="space-y-3">
          {qualityChecks.map((check, index) => (
            <QualityItem key={index} {...check} />
          ))}
        </div>
      </div>

      <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-7">
        <h3 className="font-medium text-text-primary mb-4">AI Recommendations</h3>
        
        <div className="space-y-3">
          {recommendations.map((rec, index) => (
            <div key={index} className="flex items-start gap-2 text-sm text-text-secondary">
              <ArrowRight className="w-4 h-4 text-accent-blue flex-shrink-0 mt-0.5" />
              <span>{rec}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function QualityItem({ 
  label, 
  status, 
  value 
}: { 
  label: string
  status: 'good' | 'critical' | 'warning'
  value: string 
}) {
  const statusConfig = {
    good: {
      icon: Check,
      iconColor: 'text-accent-green',
      badgeColor: 'bg-accent-green/20 text-accent-green',
      badgeText: 'GOOD'
    },
    critical: {
      icon: X,
      iconColor: 'text-accent-red',
      badgeColor: 'bg-accent-red/20 text-accent-red',
      badgeText: 'CRITICAL'
    },
    warning: {
      icon: AlertTriangle,
      iconColor: 'text-accent-amber',
      badgeColor: 'bg-accent-amber/20 text-accent-amber',
      badgeText: 'WARNING'
    }
  }

  const config = statusConfig[status]
  const Icon = config.icon

  return (
    <div className="flex items-center gap-3 text-sm">
      <Icon className={`w-4 h-4 ${config.iconColor} flex-shrink-0`} />
      <span className="text-text-secondary flex-1">{label}</span>
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${config.badgeColor}`}>
        {config.badgeText}
      </span>
      <span className="font-mono text-xs text-text-muted w-24 text-right">{value}</span>
    </div>
  )
}
