'use client'

import { AlertTriangle, RotateCw } from 'lucide-react'

/**
 * The assistant's failure state.
 *
 * Replaces a bubble that rendered the raw `error` string and nothing else. On
 * 2026-09-17 that string was an `InstructorRetryException` carrying a Groq 400
 * body, the entire `failed_generation` payload and the organisation ID — about
 * 1,500 characters of red monospace-ish text filling the chat, mid-demo.
 *
 * The backend now sends a short sentence plus a `kind` (see `user_facing_error`
 * in app.py), so the job here is to present it as a handled outcome rather than
 * a crash: a heading, the sentence, and a retry hint only where retrying is
 * actually the right advice. The `maxLength` clamp is belt-and-braces for the
 * paths the backend does not sanitise — a raw `fetch` rejection, or an older
 * server during a rolling deploy.
 */

const MAX_LENGTH = 400

/** Retrying a decommissioned model or an auth failure will not help. */
const RETRYABLE = new Set(['rate_limited', 'malformed_output', 'network', 'unknown'])

const HEADINGS: Record<string, string> = {
  rate_limited: 'Model budget temporarily exhausted',
  malformed_output: "Couldn't format the answer",
  model_gone: 'Language model unavailable',
  auth: 'Provider authentication failed',
  network: "Couldn't reach the backend",
  // Not retryable: the per-visitor limits say `rate_limited`, but the global
  // daily budget only frees up at 00:00 UTC, and the message says when.
  quota_exhausted: 'Daily demo quota reached',
  too_large: 'Question too long for the model',
}

export function ErrorBubble({ message, kind }: { message: string; kind?: string }) {
  const heading = (kind && HEADINGS[kind]) || "Couldn't complete that"
  const body =
    message.length > MAX_LENGTH ? `${message.slice(0, MAX_LENGTH)}…` : message

  return (
    <div
      role="alert"
      className="max-w-[80%] rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm"
    >
      <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-wider text-amber-400">
        <AlertTriangle className="h-3 w-3" />
        {heading}
      </div>
      {/* break-words: a long unsanitised string from an older server must wrap
          instead of forcing the chat column to scroll sideways. */}
      <p className="mt-1.5 leading-relaxed text-foreground break-words">{body}</p>
      {(!kind || RETRYABLE.has(kind)) && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <RotateCw className="h-3 w-3" />
          Ask again — this kind of failure is usually temporary.
        </p>
      )}
    </div>
  )
}
