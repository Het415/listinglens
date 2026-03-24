'use client'

const positivePhrases = [
  { text: 'noise cancellation', size: 'large' },
  { text: 'sound quality', size: 'large' },
  { text: 'comfortable', size: 'medium' },
  { text: 'premium feel', size: 'medium' },
  { text: 'easy pairing', size: 'small' },
  { text: 'carrying case', size: 'small' },
]

const negativePhrases = [
  { text: 'battery life', size: 'large' },
  { text: 'cuts out', size: 'medium' },
  { text: 'ear pain after 2 hours', size: 'medium' },
  { text: 'connection drops', size: 'medium' },
  { text: 'charging port', size: 'small' },
  { text: 'stopped working', size: 'small' },
]

interface PhraseCloudProps {
  type: 'positive' | 'negative'
}

export function PhraseClouds({ type }: PhraseCloudProps) {
  const phrases = type === 'positive' ? positivePhrases : negativePhrases
  const title = type === 'positive' ? 'Top Positive Phrases' : 'Top Negative Phrases'
  const colorClass = type === 'positive' 
    ? 'bg-accent-teal/20 text-accent-teal border-accent-teal/30' 
    : 'bg-accent-red/20 text-accent-red border-accent-red/30'

  const sizeClasses = {
    large: 'text-sm px-3 py-1.5',
    medium: 'text-xs px-2.5 py-1',
    small: 'text-xs px-2 py-0.5',
  }

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 animate-fade-up opacity-0 stagger-8">
      <h3 className="font-medium text-text-primary mb-4">{title}</h3>
      
      <div className="flex flex-wrap gap-2">
        {phrases.map((phrase, index) => (
          <span
            key={index}
            className={`rounded-lg border ${colorClass} ${sizeClasses[phrase.size as keyof typeof sizeClasses]} hover:scale-105 transition-transform cursor-default`}
          >
            {phrase.text}
          </span>
        ))}
      </div>
    </div>
  )
}
