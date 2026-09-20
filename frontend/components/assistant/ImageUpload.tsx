'use client'

import { useCallback, useRef, useState } from 'react'
import { Upload, X, Star, Loader2 } from 'lucide-react'
import type { ImageAudit } from './types'

/**
 * Upload control for a listing's images.
 *
 * Posts **straight to the audit service**, not through the ListingLens backend.
 * Proxying image bytes through that process would put it back on the image path
 * it was deliberately split off from, and a backend image proxy is both an SSRF
 * amplifier and a bandwidth bill. Thumbnails render from local
 * `createObjectURL` blobs for the same reason — nothing round-trips.
 *
 * The main-image designation is the whole point of this control. Three of the
 * compliance rules govern the main image only, and the scraped-page path cannot
 * identify it — so without a human saying which image is the main one, those
 * rules are measured but never claimed. Uploading is the only path that
 * produces real verdicts on them.
 */

const VISLENS_URL =
  process.env.NEXT_PUBLIC_VISLENS_URL?.replace(/\/$/, '') || 'http://localhost:8100'

const MAX_IMAGES = 12

type Picked = { file: File; url: string }

export function ImageUpload({
  onAudited,
  disabled,
}: {
  onAudited: (auditId: string, audit: ImageAudit) => void
  disabled?: boolean
}) {
  const [picked, setPicked] = useState<Picked[]>([])
  const [mainIndex, setMainIndex] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const addFiles = useCallback((files: FileList | null) => {
    if (!files) return
    setError(null)
    const images = Array.from(files).filter((f) => f.type.startsWith('image/'))
    if (!images.length) {
      setError('Those files are not images.')
      return
    }
    setPicked((current) => {
      const room = MAX_IMAGES - current.length
      if (room <= 0) {
        setError(`You can audit at most ${MAX_IMAGES} images at once.`)
        return current
      }
      return [
        ...current,
        ...images.slice(0, room).map((file) => ({ file, url: URL.createObjectURL(file) })),
      ]
    })
  }, [])

  const remove = useCallback((index: number) => {
    setPicked((current) => {
      // Revoke the blob URL we created, or the page leaks one per removal.
      URL.revokeObjectURL(current[index].url)
      return current.filter((_, i) => i !== index)
    })
    setMainIndex((current) => (index < current ? current - 1 : current === index ? 0 : current))
  }, [])

  const run = useCallback(async () => {
    if (!picked.length) return
    setBusy(true)
    setError(null)
    try {
      const body = new FormData()
      picked.forEach(({ file }) => body.append('files', file))
      const response = await fetch(
        `${VISLENS_URL}/audit/upload?main_index=${mainIndex}`,
        { method: 'POST', body },
      )
      if (!response.ok) {
        const detail = await response.json().catch(() => null)
        throw new Error(
          typeof detail?.detail === 'string'
            ? detail.detail
            : `the audit service returned ${response.status}`,
        )
      }
      const audit: ImageAudit = await response.json()
      if (!audit.audit_id) throw new Error('the audit service returned no audit id')
      onAudited(audit.audit_id, audit)
    } catch (e) {
      // Named plainly rather than swallowed: the service runs on its own host
      // and a cold start or a stopped process is the most likely cause.
      setError(
        e instanceof Error
          ? `Could not reach the audit service — ${e.message}`
          : 'Could not reach the audit service.',
      )
    } finally {
      setBusy(false)
    }
  }, [picked, mainIndex, onAudited])

  return (
    <div className="rounded-xl border border-border bg-background-card p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <h4 className="text-sm font-medium text-text-primary">Audit your listing images</h4>
          <p className="text-xs text-muted-foreground mt-0.5">
            Mark which one is your main image — three of Amazon&rsquo;s rules apply only to it.
          </p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled || busy}
          className="flex items-center gap-1.5 shrink-0 rounded-lg border border-border bg-background-secondary px-3 py-1.5 text-xs text-text-primary transition-colors hover:border-cyan-500/40 disabled:opacity-50"
        >
          <Upload className="w-3.5 h-3.5" />
          Choose images
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            addFiles(e.target.files)
            // Reset so picking the same file twice still fires onChange.
            e.target.value = ''
          }}
        />
      </div>

      {picked.length > 0 && (
        <>
          <div className="flex flex-wrap gap-2">
            {picked.map((item, index) => (
              <div
                key={item.url}
                className={`relative group rounded-lg border overflow-hidden ${
                  index === mainIndex ? 'border-cyan-400' : 'border-border'
                }`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={item.url}
                  alt={item.file.name}
                  className="w-16 h-16 object-cover bg-white"
                />
                <button
                  type="button"
                  onClick={() => setMainIndex(index)}
                  title="Mark as the main image"
                  className={`absolute bottom-0 left-0 right-0 flex items-center justify-center gap-0.5 py-0.5 text-[9px] font-semibold transition-colors ${
                    index === mainIndex
                      ? 'bg-cyan-500/90 text-white'
                      : 'bg-black/60 text-white/70 hover:bg-black/80'
                  }`}
                >
                  <Star className="w-2.5 h-2.5" />
                  {index === mainIndex ? 'MAIN' : 'set main'}
                </button>
                <button
                  type="button"
                  onClick={() => remove(index)}
                  title="Remove"
                  className="absolute top-0.5 right-0.5 rounded bg-black/70 p-0.5 text-white/80 opacity-0 transition-opacity group-hover:opacity-100"
                >
                  <X className="w-2.5 h-2.5" />
                </button>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={run}
            disabled={busy || disabled}
            className="mt-3 flex items-center gap-2 rounded-lg bg-cyan-500/15 border border-cyan-500/30 px-3 py-1.5 text-xs font-medium text-cyan-200 transition-colors hover:bg-cyan-500/25 disabled:opacity-50"
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
            {busy
              ? 'Auditing…'
              : `Audit ${picked.length} image${picked.length === 1 ? '' : 's'}`}
          </button>
        </>
      )}

      {error && <p className="mt-2 text-xs text-rose-300">{error}</p>}

      {picked.length === 0 && !error && (
        <p className="text-xs text-muted-foreground">
          Without uploads the audit falls back to reading the product page, which usually
          cannot tell which image is the main one — so those rules get measured but not
          judged.
        </p>
      )}
    </div>
  )
}
