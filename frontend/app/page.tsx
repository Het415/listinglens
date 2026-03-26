'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Logo } from '@/components/logo'
import { Check, Cpu, Shield, Eye, MessageSquare, TrendingUp, ArrowRight } from 'lucide-react'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(
  /\/$/,
  '',
)

const SUPPORTED_PRODUCTS = [
  { name: 'TOZO T10 Bluetooth Earbuds', asin: 'B08XPWDSWW' },
  { name: 'Fire Stick 4K', asin: 'B07GZFM1ZM' },
  { name: 'Fire TV Stick with Alexa (Previous Gen)', asin: 'B075X8471B' },
  { name: 'Echo Dot 2nd Generation', asin: 'B01K8B8YA8' },
  { name: 'Echo Dot 3rd Generation', asin: 'B07H65KP63' },
  { name: 'Fire TV Stick HD Latest Release', asin: 'B0791TX5P5' },
  { name: 'Fire Tablet 7 inch 16GB', asin: 'B010BWYDYA' },
] as const

export default function LandingPage() {
  const router = useRouter()
  const [url, setUrl] = useState('')
  const [isValidUrl, setIsValidUrl] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [loadingStep, setLoadingStep] = useState(0)
  const [showProductDropdown, setShowProductDropdown] = useState(false)
  const inputWrapRef = useRef<HTMLDivElement | null>(null)
  const isSelectingProductRef = useRef(false)

  const loadingSteps = [
    'Fetching reviews...',
    'Running NLP analysis...',
    'Building knowledge base...',
    'Generating insights...'
  ]

  useEffect(() => {
    // 1. Existing URL pattern
    const amazonUrlPattern = /^https?:\/\/(www\.)?amazon\.(com|co\.uk|de|fr|es|it|ca|com\.au|in|co\.jp)(\/.*)?$/i
    const isUrl = amazonUrlPattern.test(url) || url.includes('amazon.com/dp/')
  
    // 2. New ASIN pattern (10 alphanumeric characters)
    const isAsin = /^[A-Z0-9]{10}$/i.test(url.trim())
  
    setIsValidUrl(isUrl || isAsin)
  }, [url])

  const handleAnalyze = async () => {
    if (!isValidUrl) return
    
    setIsLoading(true)
    setLoadingStep(0)

    try {
      // step 1 — show loading state
      setLoadingStep(0) // "Fetching reviews..."
      
      const response = await fetch(`${API_URL}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url_or_asin: url }),
      })

      setLoadingStep(1) // "Running NLP analysis..."

      if (!response.ok) {
        const text = await response.text()
        let detail = text.slice(0, 400)
        try {
          const parsed = JSON.parse(text) as { detail?: string; message?: string }
          detail = parsed.detail ?? parsed.message ?? detail
        } catch {
          /* Railway/HTML error pages are not JSON */
        }
        alert(`Error (${response.status}): ${detail}`)
        setIsLoading(false)
        return
      }

      setLoadingStep(2) // "Scoring images..."
      const data = await response.json()
      
      setLoadingStep(3) // "Generating insights..."

      // store result in sessionStorage so dashboard can read it
      sessionStorage.setItem(`analysis_${data.asin}`, JSON.stringify(data))
      
      // redirect to dashboard with ASIN in URL
      router.push(`/dashboard?asin=${data.asin}`)

    } catch (err) {
      const hint =
        err instanceof Error ? err.message : 'Unknown error'
      alert(
        `Could not reach the API (${API_URL}).\n\n${hint}\n\n` +
          'Set NEXT_PUBLIC_API_URL in frontend/.env.local to your Railway URL, restart npm run dev, and check CORS + Railway logs.',
      )
      setIsLoading(false)
    }
  }

  useEffect(() => {
    if (!showProductDropdown) return

    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (!inputWrapRef.current) return
      if (!inputWrapRef.current.contains(target)) setShowProductDropdown(false)
    }

    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [showProductDropdown])

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 py-8 md:py-12">
        {/* Logo */}
        <div className="mb-12 md:mb-16">
          <Logo />
        </div>

        <div className="flex flex-col lg:flex-row gap-12 lg:gap-8">
          {/* Left side - Input and explanation (55%) */}
          <div className="lg:w-[55%] space-y-8">
            {/* Headline */}
            <div className="space-y-4">
              <h1 className="font-serif italic text-4xl md:text-[52px] leading-[1.1] text-text-primary text-balance">
                Know exactly why your product fails.
              </h1>
              <p className="text-base md:text-lg text-text-secondary max-w-xl leading-relaxed">
                Paste any Amazon product URL. Get multimodal AI analysis of your listing quality, 
                return risk, and every customer complaint — in under 30 seconds.
              </p>
            </div>

            {/* Input Component */}
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1" ref={inputWrapRef}>
                <input
                  type="url"
                  value={url}
                  onFocus={() => {
                    if (!isLoading && url.trim() === '' && !isSelectingProductRef.current) {
                      setShowProductDropdown(true)
                    }
                  }}
                  onChange={(e) => {
                    const next = e.target.value
                    setUrl(next)
                    // Hide when user starts typing; show again only when cleared.
                    setShowProductDropdown(next.trim() === '')
                  }}
                  placeholder="https://www.amazon.com/dp/B09X7CRKRX"
                  className="w-full h-14 bg-background-card border border-border rounded-xl px-4 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue focus:ring-2 focus:ring-accent-blue/20 transition-all"
                  disabled={isLoading}
                />
                {url && (
                  <div className="absolute right-4 top-1/2 -translate-y-1/2">
                    {isValidUrl ? (
                      <Check className="w-5 h-5 text-accent-green" />
                    ) : (
                      <div className="text-xs text-text-muted">Enter URL or ASIN</div>
                    )}
                  </div>
                )}

                {/* Supported product dropdown */}
                {showProductDropdown && url.trim() === '' && (
                  <div
                    className="absolute left-0 right-0 mt-2 z-50 rounded-xl border border-[#2A2A3A] bg-[#16161F] overflow-hidden shadow-lg"
                    role="listbox"
                  >
                    {SUPPORTED_PRODUCTS.map((p) => (
                      <button
                        key={p.asin}
                        type="button"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          // Prevent the input focus handler from reopening the dropdown immediately.
                          isSelectingProductRef.current = true
                          setUrl(p.asin)
                          setShowProductDropdown(false)
                          setTimeout(() => {
                            isSelectingProductRef.current = false
                          }, 0)
                        }}
                        className="w-full text-left px-4 py-3 border-b border-[#2A2A3A] last:border-b-0 hover:border-blue-500 hover:bg-[#1A1A26] transition-colors"
                      >
                        <div className="text-sm text-text-primary">{p.name}</div>
                        <div className="text-xs font-mono text-text-muted mt-0.5">
                          {p.asin}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={handleAnalyze}
                disabled={!isValidUrl || isLoading}
                className={`h-14 px-6 sm:w-[160px] bg-accent-blue text-white font-medium rounded-xl transition-all flex items-center justify-center gap-2 ${
                  isValidUrl && !isLoading 
                    ? 'animate-pulse-glow hover:bg-accent-blue/90' 
                    : 'opacity-50 cursor-not-allowed'
                }`}
              >
                {isLoading ? (
                  <span className="text-sm">{loadingSteps[loadingStep]}</span>
                ) : (
                  <>
                    <span>Analyze Product</span>
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>

            {/* Trust Indicators */}
            <div className="flex flex-wrap gap-6 text-sm text-text-secondary">
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4 text-accent-green" />
                <span>250 reviews analyzed</span>
              </div>
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-accent-blue" />
                <span>Vision + NLP + LLM</span>
              </div>
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-accent-teal" />
                <span>No account required</span>
              </div>
            </div>

            {/* Feature Cards */}
            <div className="grid sm:grid-cols-3 gap-4 pt-4">
              <FeatureCard
                icon={<Eye className="w-6 h-6 text-accent-blue" />}
                title="Visual Quality Score"
                description="CLIP model analyzes your product images for lighting, composition, and presentation quality against category benchmarks"
                delay="stagger-1"
              />
              <FeatureCard
                icon={<MessageSquare className="w-6 h-6 text-accent-teal" />}
                title="Review Intelligence"
                description="BERT sentiment analysis across 250 reviews, balanced across all star ratings. Topic clusters reveal what's driving negative feedback"
                delay="stagger-2"
              />
              <FeatureCard
                icon={<TrendingUp className="w-6 h-6 text-accent-amber" />}
                title="Return Risk Prediction"
                description="XGBoost model trained on review signals predicts your return probability and compares it against category average"
                delay="stagger-3"
              />
            </div>
          </div>

          {/* Right side - Preview (45%) */}
          <div className="lg:w-[45%]">
            <PreviewCard />
          </div>
        </div>
      </div>
    </div>
  )
}

function FeatureCard({ 
  icon, 
  title, 
  description, 
  delay 
}: { 
  icon: React.ReactNode
  title: string
  description: string
  delay: string
}) {
  return (
    <div className={`bg-background-card border border-border rounded-xl p-5 hover:border-border-hover transition-colors animate-fade-up opacity-0 ${delay}`}>
      <div className="mb-3">{icon}</div>
      <h3 className="font-medium text-text-primary mb-2">{title}</h3>
      <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
    </div>
  )
}

function PreviewCard() {
  return (
    <div className="relative rounded-2xl border-2 border-accent-blue/50 p-6 bg-background-card overflow-hidden animate-gradient-border">
      {/* Score Gauge */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <div className="relative w-20 h-20">
            <svg className="w-full h-full -rotate-90">
              <circle
                cx="40"
                cy="40"
                r="36"
                fill="none"
                stroke="#2A2A3A"
                strokeWidth="6"
              />
              <circle
                cx="40"
                cy="40"
                r="36"
                fill="none"
                stroke="#4F8EF7"
                strokeWidth="6"
                strokeDasharray={`${73 * 2.26} 226`}
                strokeLinecap="round"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="font-mono text-2xl text-accent-blue">73</span>
            </div>
          </div>
          <div>
            <div className="text-sm text-text-secondary">Overall Score</div>
            <div className="font-mono text-lg text-text-primary">/100</div>
          </div>
        </div>
        <div className="bg-accent-amber/20 text-accent-amber px-3 py-1.5 rounded-lg text-sm font-medium">
          HIGH — 34%
        </div>
      </div>

      {/* Mini Bar Chart */}
      <div className="space-y-3 mb-6">
        <div className="text-xs text-text-secondary mb-2">Sentiment Topics</div>
        <MiniBar label="Battery Life" value={42} color="red" />
        <MiniBar label="Sound Quality" value={78} color="teal" />
        <MiniBar label="Comfort" value={65} color="teal" />
        <MiniBar label="Durability" value={31} color="red" />
      </div>

      {/* Frosted Overlay */}
      <div className="absolute inset-0 bg-background-card/80 backdrop-blur-sm flex items-center justify-center">
        <div className="text-center px-6">
          <div className="w-12 h-12 rounded-full bg-accent-blue/20 flex items-center justify-center mx-auto mb-4">
            <Eye className="w-6 h-6 text-accent-blue" />
          </div>
          <p className="text-text-secondary text-sm">
            Analyze a product to unlock full report
          </p>
        </div>
      </div>
    </div>
  )
}

function MiniBar({ label, value, color }: { label: string; value: number; color: 'teal' | 'red' }) {
  const barColor = color === 'teal' ? 'bg-accent-teal' : 'bg-accent-red'
  
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-text-secondary w-24 truncate">{label}</span>
      <div className="flex-1 h-2 bg-border rounded-full overflow-hidden">
        <div 
          className={`h-full ${barColor} rounded-full`}
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="text-xs font-mono text-text-muted w-8">{value}%</span>
    </div>
  )
}
