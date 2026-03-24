'use client'

import { useEffect, useState } from 'react'

const distribution = [
  { stars: 5, count: 55, color: '#2DD4BF' },
  { stars: 4, count: 44, color: '#5EEAD4' },
  { stars: 3, count: 28, color: '#F59E0B' },
  { stars: 2, count: 31, color: '#FB923C' },
  { stars: 1, count: 89, color: '#EF4444' },
]

export function ReviewDistribution() {
  const [animate, setAnimate] = useState(false)
  const maxCount = Math.max(...distribution.map(d => d.count))

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 600)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-8">
      <h3 className="font-medium text-text-primary mb-4">Review Distribution</h3>
      
      <div className="flex items-end justify-between gap-2 h-36">
        {distribution.map((item, index) => {
          const height = (item.count / maxCount) * 100
          
          return (
            <div key={item.stars} className="flex flex-col items-center gap-2 flex-1">
              <span className="text-xs font-mono text-text-muted">{item.count}</span>
              <div className="w-full h-28 flex items-end justify-center">
                <div 
                  className="w-8 rounded-t-lg transition-all duration-700 ease-out"
                  style={{ 
                    backgroundColor: item.color,
                    height: animate ? `${height}%` : '0%',
                    transitionDelay: `${index * 80}ms`
                  }}
                />
              </div>
              <div className="flex items-center gap-0.5">
                <span className="text-xs text-text-secondary">{item.stars}</span>
                <svg className="w-3 h-3 text-accent-amber fill-current" viewBox="0 0 20 20">
                  <path d="M10 15l-5.878 3.09 1.123-6.545L.489 6.91l6.572-.955L10 0l2.939 5.955 6.572.955-4.756 4.635 1.123 6.545z" />
                </svg>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
