'use client'

export type PhraseTopicItem = {
  label: string
  keywords?: string[]
  count?: number
}

const positivePhrases = [
  { text: 'noise cancellation', size: 'large' as const },
  { text: 'sound quality', size: 'large' as const },
  { text: 'comfortable', size: 'medium' as const },
  { text: 'premium feel', size: 'medium' as const },
  { text: 'easy pairing', size: 'small' as const },
  { text: 'carrying case', size: 'small' as const },
]

const negativePhrases = [
  { text: 'battery life', size: 'large' as const },
  { text: 'cuts out', size: 'medium' as const },
  { text: 'ear pain after 2 hours', size: 'medium' as const },
  { text: 'connection drops', size: 'medium' as const },
  { text: 'charging port', size: 'small' as const },
  { text: 'stopped working', size: 'small' as const },
]

type Phrase = { text: string; size: 'large' | 'medium' | 'small' }

function buildPhrasesFromTopics(
  topics: PhraseTopicItem[],
  type: 'positive' | 'negative',
): Phrase[] {
  if (!topics.length) return []

  const sorted =
    type === 'positive'
      ? [...topics].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
      : [...topics].sort((a, b) => (a.count ?? 0) - (b.count ?? 0))

  // Positive: top 3 topics by count. Negative: bottom 3 by count.
  const picked = sorted.slice(0, 3)

  const seen = new Set<string>()
  const words: string[] = []

  for (const t of picked) {
    const ks =
      t.keywords && t.keywords.length > 0
        ? t.keywords
        : t.label
          ? [t.label]
          : []
    for (const k of ks) {
      const trimmed = k.trim()
      if (!trimmed) continue
      const key = trimmed.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      words.push(trimmed)
    }
  }

  if (!words.length) return []

  return words.map((text, i) => ({
    text,
    size: i < 2 ? 'large' : i < 4 ? 'medium' : 'small',
  }))
}

interface PhraseCloudProps {
  type: 'positive' | 'negative'
  topics?: PhraseTopicItem[]
}

export function PhraseClouds({ type, topics }: PhraseCloudProps) {
  const fromTopics =
    topics != null && Array.isArray(topics) && topics.length > 0
      ? buildPhrasesFromTopics(topics, type)
      : []

  const phrases: Phrase[] =
    fromTopics.length > 0
      ? fromTopics
      : type === 'positive'
        ? positivePhrases
        : negativePhrases

  const title = type === 'positive' ? 'Top Positive Phrases' : 'Top Negative Phrases'
  const colorClass =
    type === 'positive'
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
            key={`${phrase.text}-${index}`}
            className={`rounded-lg border ${colorClass} ${sizeClasses[phrase.size]} hover:scale-105 transition-transform cursor-default`}
          >
            {phrase.text}
          </span>
        ))}
      </div>
    </div>
  )
}
