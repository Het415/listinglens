'use client'

import { useState } from 'react'
import { Bookmark, BookmarkCheck } from 'lucide-react'
import { useSession } from '@/lib/auth-client'
import { SignInDialog } from './sign-in-dialog'

export interface SaveReportInput {
  kind: 'copilot' | 'brief'
  asin: string
  title: string
  question?: string | null
  data: object
}

/** Saves a report to the signed-in account; for a signed-out seller it opens
 *  the sign-in dialog instead. */
export function SaveReportButton({ report, className }: { report: SaveReportInput; className?: string }) {
  const { data: session } = useSession()
  const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [signInOpen, setSignInOpen] = useState(false)

  const save = async () => {
    if (!session) {
      setSignInOpen(true)
      return
    }
    setState('saving')
    setError(null)
    try {
      const res = await fetch('/api/me/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(report),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string }
        throw new Error(body.error || `Save failed (${res.status})`)
      }
      setState('saved')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
      setState('idle')
    }
  }

  const saved = state === 'saved'
  return (
    <>
      <button
        type="button"
        onClick={save}
        disabled={state !== 'idle'}
        aria-label={saved ? 'Report saved' : 'Save report'}
        title={error ?? (saved ? 'Saved to My reports' : 'Save report')}
        className={
          className ??
          'shrink-0 w-8 h-8 rounded-lg border border-border bg-background-secondary hover:border-blue-500/60 hover:text-foreground text-muted-foreground transition flex items-center justify-center disabled:cursor-default'
        }
      >
        {saved ? <BookmarkCheck className="w-4 h-4 text-emerald-400" /> : <Bookmark className="w-4 h-4" />}
      </button>
      {error && <span className="sr-only" role="status">{error}</span>}
      <SignInDialog open={signInOpen} onOpenChange={setSignInOpen} reason="to save this report" />
    </>
  )
}
