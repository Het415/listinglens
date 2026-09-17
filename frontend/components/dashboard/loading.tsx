'use client'

import { useEffect, useState } from 'react'

import { Skeleton } from '@/components/ui/skeleton'

/**
 * Shared loading states for every `/dashboard/*` surface.
 *
 * Why this exists
 * ---------------
 * The five dashboard routes had five different answers to "what does the user
 * look at while waiting": `/dashboard` spun a blue ring, the other four
 * hand-rolled `animate-pulse` blocks with slightly different shapes and
 * counts, every `<Suspense>` fallback was bare grey text (two of them spelled
 * the ellipsis differently), and the shadcn `Skeleton` primitive that already
 * existed was used by none of them.
 *
 * That inconsistency is not a cosmetic problem here. Measured against
 * production: `/analyze/{asin}` takes **11.9s** and an uncached
 * `/brief/{asin}` takes **15.3s**. For a third of a minute the loading state
 * IS the product — and `/dashboard`, the surface a demo opens first, had the
 * worst possible pairing of a 12-second wait with an indefinite spinner.
 *
 * Two rules, applied everywhere:
 *
 * 1. **Skeletons, not spinners.** A skeleton that mirrors the real layout
 *    tells you what is coming and makes the wait feel shorter; a spinner only
 *    says "something is happening". Spinners are for sub-second waits, and
 *    none of these are sub-second.
 * 2. **Say why it is slow, but never fake progress.** None of these endpoints
 *    stream — they are blocking JSON GETs, so there is no real progress to
 *    report. A determinate bar or a staged "Step 2 of 4" would be invented.
 *    Instead, after `slowAfterMs` we surface the actual reason for the wait.
 *    (`/assistant` and `/agent` DO stream `node_started` / `tool_call` /
 *    `tool_result` over SSE and render genuine per-node progress; adding that
 *    here would mean making these endpoints stream, which is a backend change
 *    and a separate piece of work.)
 */

/** One canonical skeleton surface, matching the cards these pages render.
 *
 * Built on the `Skeleton` primitive so there is a single `animate-pulse`
 * definition, but overriding its `bg-accent` / `rounded-md` — the dashboard's
 * content is bordered `bg-card` panels, and a skeleton should be the silhouette
 * of the thing it stands in for.
 */
export function SkeletonPanel({ className = '' }: { className?: string }) {
  return <Skeleton className={`rounded-xl border border-border bg-card ${className}`} />
}

/** `count` panels in a grid. `cols` must match the real grid on the page, or
 * the layout visibly jumps when content arrives — which is the one thing a
 * skeleton is supposed to prevent.
 */
export function SkeletonGrid({
  count,
  cols = 'grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4',
  height = 'h-32',
}: {
  count: number
  cols?: string
  height?: string
}) {
  return (
    <div className={`grid ${cols}`}>
      {Array.from({ length: count }, (_, i) => (
        <SkeletonPanel key={i} className={height} />
      ))}
    </div>
  )
}

/**
 * Wraps a page's skeletons and owns the waiting copy.
 *
 * `note` shows immediately and names what is loading. `slowNote` appears only
 * once the wait passes `slowAfterMs`, so a fast cached response never flashes
 * an alarming "this is taking a while" message — `/brief` is 15.3s cold and
 * 0.2s warm, and the same component has to read correctly for both.
 *
 * 4s default: long enough that a warm response never trips it, short enough
 * that the user is still wondering rather than already worried.
 */
export function DashboardLoading({
  note,
  slowNote,
  slowAfterMs = 4000,
  children,
}: {
  note: string
  slowNote?: string
  slowAfterMs?: number
  children: React.ReactNode
}) {
  const [isSlow, setIsSlow] = useState(false)

  useEffect(() => {
    if (!slowNote) return
    const t = setTimeout(() => setIsSlow(true), slowAfterMs)
    return () => clearTimeout(t)
  }, [slowNote, slowAfterMs])

  return (
    <div className="space-y-4" role="status" aria-live="polite" aria-busy="true">
      {/* Above the skeletons, not below them. `/dashboard`'s skeleton stack is
          ~700px tall, so a trailing caption lands below the fold on a laptop
          viewport — which is precisely where a "why is this slow" message is
          useless. Leading it also means the explanation is the first thing
          read rather than the last. */}
      <div className="space-y-1 text-center">
        <p className="text-xs text-muted-foreground">{note}</p>
        {/* Reserve the second line's height up front so revealing it does not
            shift the skeletons below. */}
        <p className="min-h-4 text-xs text-muted-foreground/70">
          {isSlow && slowNote ? slowNote : ' '}
        </p>
      </div>
      {children}
    </div>
  )
}

/**
 * `<Suspense>` fallback for the dashboard routes.
 *
 * These boundaries exist because `useSearchParams()` bails the whole page out
 * of static prerendering without one — so in practice this renders for a
 * single frame on the client, not for a measurable wait. It still gets a
 * skeleton rather than the word "Loading...": the previous bare text meant
 * every dashboard route began with a flash of unstyled grey copy before the
 * real loading state replaced it.
 */
export function RouteFallback() {
  return (
    <div className="space-y-6 p-4 md:p-6" role="status" aria-busy="true">
      <SkeletonGrid count={4} />
      <SkeletonPanel className="h-64" />
    </div>
  )
}
