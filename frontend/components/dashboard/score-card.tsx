'use client'

import { useEffect, useState } from 'react'
import { Star } from 'lucide-react'

interface ScoreCardProps {
  title: string
  value: number
  suffix?: string
  color?: 'blue' | 'amber' | 'teal' | 'default'
  progress?: number
  badge?: string
  stars?: number
  subtext?: string
  subtextColor?: 'green' | 'red' | 'default'
  delay?: number
}

export function ScoreCard({
  title,
  value,
  suffix = '',
  color = 'default',
  progress,
  badge,
  stars,
  subtext,
  subtextColor = 'default',
  delay = 1
}: ScoreCardProps) {
  const [displayValue, setDisplayValue] = useState(0)
  const [progressWidth, setProgressWidth] = useState(0)

  const colorClasses = {
    blue: 'text-accent-blue',
    amber: 'text-accent-amber',
    teal: 'text-accent-teal',
    default: 'text-text-primary'
  }

  const subtextColorClasses = {
    green: 'text-accent-green',
    red: 'text-accent-red',
    default: 'text-text-secondary'
  }

  useEffect(() => {
    const duration = 1200
    const steps = 60
    const increment = value / steps
    let current = 0
    
    const timer = setInterval(() => {
      current += increment
      if (current >= value) {
        setDisplayValue(value)
        clearInterval(timer)
      } else {
        setDisplayValue(Math.round(current * 10) / 10)
      }
    }, duration / steps)

    return () => clearInterval(timer)
  }, [value])

  useEffect(() => {
    if (progress !== undefined) {
      const timer = setTimeout(() => {
        setProgressWidth(progress)
      }, 100)
      return () => clearTimeout(timer)
    }
  }, [progress])

  return (
    <div 
      className={`bg-background-card border border-border rounded-xl p-5 hover:border-border-hover transition-colors animate-fade-up opacity-0 stagger-${delay}`}
    >
      <div className="text-sm text-text-secondary mb-3">{title}</div>
      
      <div className="flex items-baseline gap-1 mb-3">
        <span className={`font-mono text-5xl ${colorClasses[color]}`}>
          {displayValue % 1 === 0 ? Math.round(displayValue) : displayValue.toFixed(1)}
        </span>
        <span className="text-text-muted text-lg">{suffix}</span>
      </div>

      {progress !== undefined && (
        <div className="h-1.5 bg-border rounded-full overflow-hidden mb-3">
          <div 
            className={`h-full ${color === 'blue' ? 'bg-accent-blue' : color === 'teal' ? 'bg-accent-teal' : 'bg-accent-amber'} rounded-full transition-all duration-800 ease-out`}
            style={{ width: `${progressWidth}%` }}
          />
        </div>
      )}

      {badge && (
        <div className="inline-flex px-2.5 py-1 bg-accent-amber/20 text-accent-amber text-xs font-medium rounded-md mb-3">
          {badge}
        </div>
      )}

      {stars !== undefined && (
        <div className="flex gap-0.5 mb-3">
          {[1, 2, 3, 4, 5].map((star) => (
            <Star
              key={star}
              className={`w-4 h-4 ${
                star <= Math.floor(stars)
                  ? 'fill-accent-amber text-accent-amber'
                  : star - 1 < stars
                  ? 'fill-accent-amber/50 text-accent-amber'
                  : 'text-border'
              }`}
            />
          ))}
        </div>
      )}

      {subtext && (
        <div className={`text-xs ${subtextColorClasses[subtextColor]}`}>
          {subtext}
        </div>
      )}
    </div>
  )
}
