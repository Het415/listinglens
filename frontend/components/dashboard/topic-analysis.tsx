'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

const topics = [
  { name: 'Battery Life', positive: 18, negative: 67 },
  { name: 'Sound Quality', positive: 89, negative: 8 },
  { name: 'Noise Cancellation', positive: 76, negative: 14 },
  { name: 'Comfort & Fit', positive: 52, negative: 38 },
  { name: 'Build Quality', positive: 61, negative: 29 },
  { name: 'Price vs Value', positive: 44, negative: 41 },
]

export function TopicAnalysis() {
  const [animate, setAnimate] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 300)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-5">
      <h3 className="font-medium text-text-primary mb-1">Review Topic Analysis</h3>
      <p className="text-sm text-text-secondary mb-6">What customers are actually talking about</p>
      
      <div className="space-y-4">
        {topics.map((topic, index) => (
          <TopicBar 
            key={topic.name} 
            topic={topic} 
            animate={animate}
            delay={index * 100}
          />
        ))}
      </div>

      <div className="mt-6 flex items-start gap-3 p-4 bg-accent-amber/10 border-l-2 border-accent-amber rounded-r-lg">
        <AlertTriangle className="w-4 h-4 text-accent-amber flex-shrink-0 mt-0.5" />
        <p className="text-sm text-text-secondary">
          Battery life complaints appear in 67% of negative reviews — this is your highest return risk factor
        </p>
      </div>
    </div>
  )
}

function TopicBar({ 
  topic, 
  animate, 
  delay 
}: { 
  topic: typeof topics[0]
  animate: boolean
  delay: number 
}) {
  const [widths, setWidths] = useState({ positive: 0, negative: 0 })

  useEffect(() => {
    if (animate) {
      const timer = setTimeout(() => {
        setWidths({ positive: topic.positive, negative: topic.negative })
      }, delay)
      return () => clearTimeout(timer)
    }
  }, [animate, topic, delay])

  return (
    <div className="flex items-center gap-4">
      <div className="w-32 text-sm text-text-secondary truncate">{topic.name}</div>
      
      <div className="flex-1 flex items-center gap-2">
        <span className="text-xs font-mono text-accent-teal w-8 text-right">{topic.positive}%</span>
        <div className="flex-1 flex gap-1">
          <div className="flex-1 h-3 bg-border/50 rounded-full overflow-hidden">
            <div 
              className="h-full bg-accent-teal rounded-full transition-all duration-700 ease-out"
              style={{ width: `${widths.positive}%` }}
            />
          </div>
          <div className="flex-1 h-3 bg-border/50 rounded-full overflow-hidden">
            <div 
              className="h-full bg-accent-red rounded-full transition-all duration-700 ease-out"
              style={{ width: `${widths.negative}%` }}
            />
          </div>
        </div>
        <span className="text-xs font-mono text-accent-red w-8">{topic.negative}%</span>
      </div>
    </div>
  )
}
