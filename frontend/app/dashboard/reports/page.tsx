'use client'

import { useCallback, useEffect, useState } from 'react'
import { FolderOpen, Trash2, ArrowLeft, FileText, Sparkles } from 'lucide-react'
import { useSession } from '@/lib/auth-client'
import { SignInDialog } from '@/components/auth/sign-in-dialog'
import { RecommendationCard } from '@/components/assistant/RecommendationCard'
import { BriefView } from '@/components/dashboard/brief-view'
import { savedView, type Report, type ReportSummary } from '@/lib/saved'

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function SavedReport({ report }: { report: Report }) {
  const view = savedView(report)
  if (view.type === 'copilot') return <RecommendationCard rec={view.rec} />
  // A saved brief is a snapshot; the live one may have moved on since.
  if (view.type === 'brief') return <BriefView data={view.brief} footnote={`numbers as of ${formatDate(report.created_at)}`} />
  // Saved by an older (or newer) version of the app whose shape this build
  // doesn't know. Show what's certain instead of crashing a card.
  const data = report.payload?.data as { summary?: unknown } | undefined
  return (
    <div className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
      <p className="mb-2 font-medium text-foreground">This report was saved with a different version of ListingLens.</p>
      {typeof data?.summary === 'string' && <p>{data.summary}</p>}
    </div>
  )
}

export default function ReportsPage() {
  const { data: sessionData, isPending: sessionPending } = useSession()
  // Everything below depends on the session, which only the browser knows;
  // treat it as unknown until mounted so the first render matches the server.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const session = mounted ? sessionData : null
  const isPending = !mounted || sessionPending
  const [signInOpen, setSignInOpen] = useState(false)
  const [reports, setReports] = useState<ReportSummary[] | null>(null)
  const [open, setOpen] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch('/api/me/reports')
      if (!res.ok) throw new Error(`Could not load reports (${res.status})`)
      setReports(((await res.json()) as { reports: ReportSummary[] }).reports)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load reports')
    }
  }, [])

  useEffect(() => {
    if (session) void load()
  }, [session, load])

  const openReport = async (id: string) => {
    setError(null)
    const res = await fetch(`/api/me/reports/${id}`)
    if (!res.ok) return setError('That report no longer exists.')
    setOpen(((await res.json()) as { report: Report }).report)
  }

  const remove = async (id: string) => {
    const res = await fetch(`/api/me/reports/${id}`, { method: 'DELETE' })
    if (!res.ok && res.status !== 404) return setError('Could not delete the report.')
    setReports((cur) => cur?.filter((r) => r.id !== id) ?? null)
    if (open?.id === id) setOpen(null)
  }

  return (
    <div className="min-h-screen space-y-6 bg-background p-4 text-foreground md:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-medium">
          <FolderOpen className="h-5 w-5 text-accent-blue" /> My reports
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Copilot recommendations and executive briefs you saved. Chats you have while signed in are kept
          too, and come back when you reopen a product in the AI Assistant.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">{error}</div>
      )}

      {!isPending && !session && (
        <div className="rounded-xl border border-border bg-card p-6 text-sm">
          <p className="text-muted-foreground">Sign in to see the reports you&apos;ve saved.</p>
          <button
            type="button"
            onClick={() => setSignInOpen(true)}
            className="mt-4 rounded-lg bg-accent-teal px-4 py-2 font-medium text-white hover:bg-accent-teal/90"
          >
            Sign in
          </button>
          <SignInDialog open={signInOpen} onOpenChange={setSignInOpen} />
        </div>
      )}

      {session && open && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setOpen(null)}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> All reports
          </button>
          <div>
            <h2 className="text-lg font-medium">{open.title}</h2>
            <p className="text-xs text-muted-foreground">
              ASIN {open.asin} · saved {formatDate(open.created_at)}
              {open.question ? ` · “${open.question}”` : ''}
            </p>
          </div>
          <SavedReport report={open} />
        </div>
      )}

      {session && !open && reports && reports.length === 0 && (
        <div className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          Nothing saved yet. Use the bookmark button on a Copilot recommendation or an executive brief.
        </div>
      )}

      {session && !open && reports && reports.length > 0 && (
        <ul className="divide-y divide-border rounded-xl border border-border bg-card">
          {reports.map((r) => (
            <li key={r.id} className="flex items-center gap-3 p-4">
              {r.kind === 'brief' ? (
                <FileText className="h-4 w-4 shrink-0 text-accent-blue" />
              ) : (
                <Sparkles className="h-4 w-4 shrink-0 text-accent-teal" />
              )}
              <button type="button" onClick={() => openReport(r.id)} className="min-w-0 flex-1 text-left">
                <div className="truncate text-sm font-medium text-foreground">{r.title}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {formatDate(r.created_at)}
                  {r.question ? ` · “${r.question}”` : ''}
                </div>
              </button>
              <button
                type="button"
                onClick={() => remove(r.id)}
                aria-label={`Delete ${r.title}`}
                className="rounded-lg p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
