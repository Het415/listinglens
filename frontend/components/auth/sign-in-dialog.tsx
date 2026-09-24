'use client'

import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { signIn } from '@/lib/auth-client'

type Provider = 'google' | 'github'

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" aria-hidden>
      <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.24 1.4-1.7 4.1-5.5 4.1-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.5 14.6 2.5 12 2.5 6.8 2.5 2.6 6.7 2.6 12s4.2 9.5 9.4 9.5c5.4 0 9-3.8 9-9.2 0-.6-.1-1.1-.2-1.6H12z" />
    </svg>
  )
}

function GitHubMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden>
      <path d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.3 4.7 18.3 5 18.3 5c.7 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.2c0 .3.2.7.8.6A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5z" />
    </svg>
  )
}

export function SignInDialog({
  open,
  onOpenChange,
  reason,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Why we're asking, e.g. "to save this report". */
  reason?: string
}) {
  const [pending, setPending] = useState<Provider | null>(null)
  const [error, setError] = useState<string | null>(null)

  const go = async (provider: Provider) => {
    setPending(provider)
    setError(null)
    // Back to the exact page (and ?asin=) the seller was on.
    const res = await signIn.social({ provider, callbackURL: window.location.href })
    if (res?.error) {
      setError(res.error.message || 'Sign-in failed. Try the other option.')
      setPending(null)
    }
    // On success the browser is already navigating to the provider.
  }

  const buttonClass =
    'flex w-full items-center justify-center gap-3 rounded-lg border border-border bg-background-card px-4 py-2.5 text-sm font-medium text-text-primary transition-colors hover:border-border-hover disabled:opacity-60'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Sign in to ListingLens</DialogTitle>
          <DialogDescription>
            {reason ? `Sign in ${reason}. ` : ''}Analysis works without an account; signing in keeps
            your saved reports and chats across sessions.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <button type="button" className={buttonClass} disabled={pending !== null} onClick={() => go('google')}>
            <GoogleMark />
            {pending === 'google' ? 'Redirecting…' : 'Continue with Google'}
          </button>
          <button type="button" className={buttonClass} disabled={pending !== null} onClick={() => go('github')}>
            <GitHubMark />
            {pending === 'github' ? 'Redirecting…' : 'Continue with GitHub'}
          </button>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <p className="text-xs text-muted-foreground">
          We store your name, email, and the reports and chats you save. You can delete any of it, or
          your whole account, from the account menu.
        </p>
      </DialogContent>
    </Dialog>
  )
}
