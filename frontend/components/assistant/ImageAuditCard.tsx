'use client'

import { ImageIcon, AlertTriangle, Copy, Info } from 'lucide-react'
import { checkStatusStyle } from './style-helpers'
import type { ImageAudit, ImageAuditResult } from './types'

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

export function ImageAuditCard({ result }: { result: ImageAuditResult }) {
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
    g.f.map((finding) => ({ finding, images: g.i })),
  )
  const measuredOnly = audit.groups.reduce((n, g) => n + (g.n_measured_only ?? 0), 0)
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

      {/* Verdicts. Only rules that were actually broken appear here. */}
      {verdicts.length > 0 ? (
        <div className="space-y-2">
          {verdicts.map(({ finding, images }, index) => {
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
                    {shown && <span className="ml-2 font-mono text-xs text-cyan-300">{shown}</span>}
                  </div>
                  {/* The rule as the service stated it — never reworded here. */}
                  {entry?.rule && (
                    <div className="text-xs text-muted-foreground mt-0.5">{entry.rule}</div>
                  )}
                  <div className="text-[11px] text-muted-foreground mt-0.5">
                    image{images.length === 1 ? '' : 's'} {images.map((i) => i + 1).join(', ')}
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
                    <span className="ml-2 font-mono text-xs text-cyan-300">{value}</span>
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
