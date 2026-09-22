'use client'

import { ImageIcon, AlertTriangle, Copy, Info } from 'lucide-react'
import { checkStatusStyle } from './style-helpers'
import type {
  AuditDetail,
  ImageAudit,
  ImageAuditResult,
  PickedImageMeta,
} from './types'

/**
 * Renders an `image_audit` result.
 *
 * The whole design problem here is the same one the payload solves: a
 * measurement must not be able to read as a violation. So this component
 * renders **verdicts only** as findings, shows the measured-only count as a
 * neutral aside, and surfaces the caveat prominently when no main image was
 * identified. It never re-derives or re-words a verdict — the rule text and the
 * measured value both come from the service.
 *
 * A live agent run demonstrated why that matters: given advisory measurements
 * in the same shape as verdicts, an LLM reported every one as a violation
 * despite an explicit instruction not to. A UI has the same failure mode with a
 * human reader, so the distinction is carried visually and not just in a field.
 *
 * `images` and `detail` are optional enrichments, and the rule for both is the
 * same: they may explain a verdict, never create one. `verdicts` below stays
 * derived from `audit.groups[].f` — the compact payload — because that is the
 * only source where an advisory measurement has had its status neutralised.
 * `detail.images[].checks` carries RAW statuses, so a compliant lifestyle photo
 * appears there as `status: "fail", tier: "advisory"`; enumerating it would
 * reintroduce the exact bug this component was built to prevent. See the
 * warning on AuditCheckDetail.
 *
 * Both are absent on the agent path (TracePanel renders a tool result with no
 * blob URLs and no detail record), so every use of them degrades to the
 * original rendering.
 */

function statusFromFinding(finding: [string, string, number?]): string {
  return finding[1]
}

function formatValue(code: string, value: number | undefined): string | null {
  if (value === undefined) return null
  // Fractions are rendered as percentages where the rule is a percentage, and
  // left alone where it is a count or a pixel dimension.
  if (code === 'wbg' || code === 'occ') return `${(value * 100).toFixed(1)}%`
  if (code === 'asp') return `${value.toFixed(2)}:1`
  if (code === 'res') return `${value.toFixed(0)}px`
  return `${value}`
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function Unavailable({ result }: { result: ImageAuditResult }) {
  const blocked = result.status === 'blocked'
  const malformed = result.status === 'ok'
  return (
    <div className="bg-background-card border border-border rounded-xl p-5">
      <div className="flex items-center gap-2 mb-2">
        <ImageIcon className="w-4 h-4 text-cyan-400" />
        <h3 className="font-medium text-text-primary">Listing image audit</h3>
      </div>
      <div className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-6">
        <p className="text-sm text-muted-foreground">
          {blocked
            ? 'Could not read this listing’s images.'
            : malformed
              ? 'The image audit returned an unexpected shape.'
              : 'The image audit did not run.'}
        </p>
        {result.reason && (
          <p className="mt-1 text-xs text-muted-foreground">{result.reason}</p>
        )}
        {blocked && (
          <p className="mt-2 text-xs text-muted-foreground">
            Upload the image files directly for a reliable audit.
          </p>
        )}
      </div>
    </div>
  )
}

export function ImageAuditCard({
  result,
  images,
  detail,
}: {
  result: ImageAuditResult
  images?: PickedImageMeta[]
  detail?: AuditDetail | null
}) {
  // `!result.audit.groups` is not paranoia: the first wiring of this card
  // passed the tool's outer wrapper instead of the inner audit, and the
  // resulting `undefined.flatMap` crashed the whole assistant page rather than
  // degrading one card. A malformed payload now renders the unavailable state.
  if (result.status !== 'ok' || !result.audit || !Array.isArray(result.audit.groups)) {
    return <Unavailable result={result} />
  }

  const audit: ImageAudit = result.audit
  const headline = checkStatusStyle(audit.headline)
  const verdicts = audit.groups.flatMap((g) =>
    g.f.map((finding) => ({ finding, groupImages: g.i })),
  )
  const measuredOnly = audit.groups.reduce((n, g) => n + (g.n_measured_only ?? 0), 0)
  // Per-image facts, merged service-first. The service's dimensions are the
  // ones its verdicts were computed from; the browser only has the pixels.
  const perImage = Array.from({ length: audit.n_images }, (_, i) => {
    const d = detail?.images?.[i]
    const c = images?.[i]
    return {
      url: c?.url ?? null,
      width: d?.orig_width ?? c?.width ?? null,
      height: d?.orig_height ?? c?.height ?? null,
      format: d?.format ?? c?.type?.split('/')[1]?.toUpperCase() ?? null,
      size: d?.n_bytes ?? c?.size ?? null,
    }
  })
  const showStrip = perImage.some((p) => p.url || p.width)

  /** The service's own sentence for a code that is ALREADY a verdict.
   *
   * Returned verbatim. Composing our own ("too small for Amazon", "re-export at
   * 1000px") would be this component re-wording a verdict, which it does not
   * do. Returns null unless every image in the group gives the same sentence —
   * `white_background`'s reason names a modal RGB that is not part of the
   * grouping signature, so two images can share a verdict without sharing an
   * explanation, and attributing one image's pixels to another would be a
   * fabricated finding.
   */
  const reasonFor = (code: string, imgs: number[]): string | null => {
    if (!detail?.images) return null
    const checkId = audit.legend[code]?.check
    if (!checkId) return null
    const reasons = new Set(
      imgs.map((i) => detail.images[i]?.checks?.find((c) => c.check_id === checkId)?.reason ?? ''),
    )
    if (reasons.size !== 1) return null
    const [only] = [...reasons]
    return only || null
  }

  const duplicates = audit.duplicates
  const clusters = duplicates?.clusters ?? []
  const setChecks = audit.set_checks ?? []

  return (
    <div className="bg-background-card border border-border rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <ImageIcon className="w-4 h-4 text-cyan-400 shrink-0" />
          <h3 className="font-medium text-text-primary truncate">Listing image audit</h3>
        </div>
        <span
          className={`text-[10px] font-semibold px-2 py-0.5 rounded border shrink-0 ${headline.cls}`}
        >
          {headline.label}
        </span>
      </div>

      <p className="text-xs text-muted-foreground">
        {audit.n_images} image{audit.n_images === 1 ? '' : 's'} checked against Amazon’s published
        requirements · rules {audit.rules_version}
        {audit.main_index !== null && ` · image ${audit.main_index + 1} treated as the main image`}
      </p>

      {/* The caveat is not a footnote. Without it a reader concludes things
          about rules that were never evaluated. */}
      {audit.caveat && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5">
          <Info className="w-4 h-4 text-amber-300 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-100/90 leading-relaxed">{audit.caveat}</p>
        </div>
      )}

      {/* What was actually audited. Deliberately free of any status vocabulary:
          these are measurements, and a dimension rendered in a verdict colour
          is the same category error the payload design exists to prevent. The
          numbers alone do the explaining — `resolution_and_format` reports the
          LONGEST SIDE, so "92 × 65" next to the thumbnail makes a bare "92px"
          self-evident without a word of new prose. */}
      {showStrip && (
        <div className="flex flex-wrap gap-2">
          {perImage.map((img, i) => (
            <div
              key={i}
              className={`flex items-center gap-2.5 rounded-lg border bg-background-secondary px-2.5 py-2 ${
                i === audit.main_index ? 'border-accent-teal/50' : 'border-border'
              }`}
            >
              {img.url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={img.url}
                  alt={`image ${i + 1}`}
                  className="w-12 h-12 object-contain bg-white rounded shrink-0"
                />
              ) : (
                <div className="w-12 h-12 rounded bg-muted/40 shrink-0" />
              )}
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-text-primary">image {i + 1}</span>
                  {i === audit.main_index && (
                    <span className="text-[9px] font-semibold px-1 py-px rounded bg-accent-teal/10 text-accent-teal border border-accent-teal/30">
                      MAIN
                    </span>
                  )}
                </div>
                {img.width && img.height && (
                  <div className="font-mono text-[11px] text-muted-foreground mt-0.5">
                    {img.width} × {img.height}
                  </div>
                )}
                {(img.format || img.size !== null) && (
                  <div className="text-[10px] text-muted-foreground/70 mt-px">
                    {[img.format, img.size !== null ? formatBytes(img.size) : null]
                      .filter(Boolean)
                      .join(' · ')}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Verdicts. Only rules that were actually broken appear here. */}
      {verdicts.length > 0 ? (
        <div className="space-y-2">
          {verdicts.map(({ finding, groupImages }, index) => {
            const [code, , value] = finding
            const entry = audit.legend[code]
            const style = checkStatusStyle(statusFromFinding(finding))
            const shown = formatValue(code, value)
            return (
              <div
                key={`${code}-${index}`}
                className="flex items-start gap-3 rounded-lg border border-border bg-background-secondary px-3 py-2.5"
              >
                <span
                  className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border shrink-0 mt-0.5 ${style.cls}`}
                >
                  {style.label}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-text-primary">
                    {entry?.check ?? code}
                    {/* The measured value is the number the reader came for, so
                        it uses the theme-aware accent rather than a hardcoded
                        dark-theme cyan that washes out on a light background. */}
                    {shown && (
                      <span className="ml-2 font-mono text-xs font-semibold text-accent-teal">
                        {shown}
                      </span>
                    )}
                  </div>
                  {/* The rule as the service stated it — never reworded here. */}
                  {entry?.rule && (
                    <div className="text-xs text-muted-foreground mt-0.5">{entry.rule}</div>
                  )}
                  {/* And the service's own explanation of what it measured, also
                      verbatim. Distinguished from the rule by opacity rather
                      than a label: any label would have to be a severity or a
                      remedy word, and this component states neither. */}
                  {reasonFor(code, groupImages) && (
                    <div className="text-xs text-muted-foreground/70 mt-1 leading-relaxed">
                      {reasonFor(code, groupImages)}
                    </div>
                  )}
                  <div className="text-[11px] text-muted-foreground mt-0.5">
                    image{groupImages.length === 1 ? '' : 's'}{' '}
                    {groupImages.map((i) => i + 1).join(', ')}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-5 text-center">
          <p className="text-sm text-muted-foreground">No rules were broken.</p>
        </div>
      )}

      {/* Set-level checks, e.g. how many images were supplied. */}
      {setChecks.length > 0 && (
        <div className="space-y-2">
          {setChecks.map((finding, index) => {
            const [code, , value] = finding
            const entry = audit.legend[code]
            const style = checkStatusStyle(statusFromFinding(finding))
            return (
              <div
                key={`set-${code}-${index}`}
                className="flex items-center gap-3 rounded-lg border border-border bg-background-secondary px-3 py-2"
              >
                <span
                  className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border shrink-0 ${style.cls}`}
                >
                  {style.label}
                </span>
                <span className="text-sm text-text-primary">
                  {entry?.check ?? code}
                  {value !== undefined && (
                    <span className="ml-2 font-mono text-xs font-semibold text-accent-teal">
                      {value}
                    </span>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Duplicates. Reported with the method and threshold, so the claim is
          attributable to a specific calibration rather than floating free. */}
      {duplicates && !duplicates.unavailable && clusters.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <Copy className="w-3.5 h-3.5 text-amber-300" />
            <span className="text-sm text-text-primary">
              {clusters.length} duplicate image {clusters.length === 1 ? 'set' : 'sets'}
            </span>
          </div>
          <ul className="mt-1.5 space-y-0.5">
            {clusters.map((cluster, index) => (
              <li key={index} className="text-xs text-muted-foreground">
                images {cluster.map((i) => i + 1).join(' and ')} are the same photo
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-muted-foreground mt-1.5">
            detected by {duplicates.method} at distance ≤ {duplicates.threshold}
          </p>
        </div>
      )}

      {duplicates?.unavailable && (
        <p className="text-xs text-muted-foreground">
          Duplicate detection unavailable: {duplicates.unavailable}
        </p>
      )}

      {duplicates?.group_mismatches?.length ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-300" />
            <span className="text-sm text-text-primary">Possible wrong-SKU images</span>
          </div>
          <ul className="mt-1.5 space-y-0.5">
            {duplicates.group_mismatches.map((m) => (
              <li key={m.i} className="text-xs text-muted-foreground">
                image {m.i + 1} is tagged {m.tagged} but matches {m.nearest}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* The measured-only count, stated as an absence of a verdict rather than
          a mild one. Values live behind the audit id, not here. */}
      {measuredOnly > 0 && (
        <p className="text-[11px] text-muted-foreground border-t border-border pt-2.5">
          {measuredOnly} further measurement{measuredOnly === 1 ? '' : 's'} taken that{' '}
          {measuredOnly === 1 ? 'is' : 'are'} not rule verdicts — main-image rules do not apply to
          secondary images, which may use lifestyle backgrounds, props and text.
        </p>
      )}

      {audit.notes?.length ? (
        <ul className="space-y-0.5 border-t border-border pt-2.5">
          {audit.notes.map((note, index) => (
            <li key={index} className="text-[11px] text-muted-foreground">
              {note}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
