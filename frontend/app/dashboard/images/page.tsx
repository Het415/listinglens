'use client'

import Link from 'next/link'
import { Suspense, useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ArrowRight, ImageIcon } from 'lucide-react'

import { ImageUpload } from '@/components/assistant/ImageUpload'
import { ImageAuditCard } from '@/components/assistant/ImageAuditCard'
import { RouteFallback } from '@/components/dashboard/loading'
import type { AuditDetail, ImageAudit, PickedImageMeta } from '@/components/assistant/types'

/**
 * The listing image audit, as its own page.
 *
 * It lived inside Copilot mode on /assistant, which made it four clicks from
 * the front door and — more to the point — put it behind the one flow that
 * needs a catalog ASIN and a multi-minute review pipeline. This audit needs
 * neither: the browser posts the files straight to the audit service, and the
 * verdicts are arithmetic over pixels. It is the only feature here that works
 * on a seller's own product rather than on one of twelve demo ASINs, so it gets
 * a page instead of a tab inside a mode of something else.
 *
 * `?asin=` is therefore OPTIONAL and its absence is an ordinary state, not demo
 * mode. Deliberately no DemoModeBanner: there is nothing demo about auditing
 * your own images, and the sidebar appends the param anyway when one is set,
 * which is only used to carry context into the Copilot hand-off below.
 */

const STORE_KEY = 'image_audit_last'

type Stored = { auditId: string; audit: ImageAudit; detail: AuditDetail | null }

function ImagesInner() {
  const searchParams = useSearchParams()
  const asinParam = searchParams.get('asin')

  const [auditId, setAuditId] = useState<string | null>(null)
  const [audit, setAudit] = useState<ImageAudit | null>(null)
  const [images, setImages] = useState<PickedImageMeta[]>([])
  const [detail, setDetail] = useState<AuditDetail | null>(null)

  // Rehydrate the last audit so a stray reload or a trip to another page does
  // not throw away a twelve-image upload. Thumbnails are NOT persisted: they
  // are blob URLs, which die with the document, and a stored one would render
  // as a broken image. The card already treats them as optional, so it comes
  // back without the strip and keeps the verdicts and their explanations.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(STORE_KEY)
      if (!raw) return
      const parsed: Stored = JSON.parse(raw)
      if (!parsed?.audit?.groups) return
      setAuditId(parsed.auditId)
      setAudit(parsed.audit)
      setDetail(parsed.detail ?? null)
    } catch {
      // Malformed or unavailable storage is not worth surfacing.
    }
  }, [])

  const handleAudited = useCallback(
    (id: string, result: ImageAudit, imgs: PickedImageMeta[], d: AuditDetail | null) => {
      setAuditId(id)
      setAudit(result)
      setImages(imgs)
      setDetail(d)
      try {
        sessionStorage.setItem(STORE_KEY, JSON.stringify({ auditId: id, audit: result, detail: d }))
      } catch {
        // ignore
      }
    },
    [],
  )

  // The hand-off carries the audit ID, not the payload: the agent's image_audit
  // tool re-reads it from the service, and a payload in a query string would put
  // measured values in the URL.
  const copilotHref = (() => {
    const params = new URLSearchParams()
    if (asinParam) params.set('asin', asinParam)
    params.set('mode', 'copilot')
    if (auditId) params.set('audit', auditId)
    params.set('q', 'What should I fix about my listing images?')
    return `/assistant?${params.toString()}`
  })()

  return (
    <div className="p-4 md:p-6 space-y-5 max-w-4xl">
      <div>
        <div className="flex items-center gap-2">
          <ImageIcon className="w-5 h-5 text-cyan-400" />
          <h1 className="text-lg font-medium text-text-primary">Listing image audit</h1>
        </div>
        <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
          Upload your product photos and have them checked against Amazon&apos;s published
          main-image requirements. No ASIN needed, and nothing is stored — the checks are
          arithmetic over the pixels, so the same files always give the same answer.
        </p>
      </div>

      <ImageUpload onAudited={handleAudited} standalone />

      {audit && (
        <>
          <ImageAuditCard
            result={{ asin: asinParam ?? '', status: 'ok', reason: '', audit }}
            images={images}
            detail={detail}
          />
          <Link
            href={copilotHref}
            className="inline-flex items-center gap-1.5 text-sm text-accent-teal hover:underline"
          >
            Ask the Copilot what to do about this
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </>
      )}
    </div>
  )
}

export default function ImagesPage() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <ImagesInner />
    </Suspense>
  )
}
