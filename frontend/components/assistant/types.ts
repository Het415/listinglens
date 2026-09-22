// Shared types for the assistant surfaces (/chat, /agent, /assistant).

export interface SourceItem {
  text: string
  rating: number | string
  sentiment: string
  score: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content?: string
  sources?: SourceItem[]
  recommendation?: Recommendation
  error?: string
  /**
   * Error class from the backend (`rate_limited`, `malformed_output`,
   * `model_gone`, `auth`, `unknown`). Drives the retry hint — suggesting
   * "try again" on a decommissioned model would be wrong.
   */
  errorKind?: string
}

export type EvidenceItem = { tool: string; snippet: string; relevance: number }

export type Recommendation = {
  decision: 'go' | 'no_go' | 'needs_more_data'
  confidence: number
  summary: string
  reasoning_steps: string[]
  evidence: EvidenceItem[]
  risks: string[]
  suggested_next_actions: string[]
  /**
   * True when the backend assembled this from tool results because the
   * Synthesizer LLM failed. The evidence is real; `decision` and `confidence`
   * are placeholders, so the card must say so rather than render 0% next to a
   * confident-looking verdict.
   */
  degraded?: boolean
}

/** The `image_audit` tool's payload, as the vislens service emits it.
 *
 * Mirrors the wire shape deliberately rather than flattening it: the
 * verdict-vs-measurement distinction is carried structurally (`f` vs
 * `n_measured_only`), and re-shaping it here would create a second place for
 * that semantics to drift.
 */
export type AuditFinding = [code: string, status: string, value?: number]

export type AuditGroup = {
  i: number[]
  n_pass: number
  f: AuditFinding[]
  n_measured_only?: number
}

export type ImageAudit = {
  rules_version: string
  audit_id: string | null
  n_images: number
  headline: 'pass' | 'warn' | 'fail' | 'skipped'
  main_index: number | null
  caveat: string | null
  legend: Record<string, { check: string; rule: string }>
  groups: AuditGroup[]
  set_checks: AuditFinding[]
  duplicates?: {
    method: string | null
    threshold: number | null
    clusters: number[][]
    unavailable?: string
    skipped_no_contrast?: number[]
    group_mismatches?: { i: number; tagged: string; nearest: string }[]
  }
  notes?: string[]
}

export type ImageAuditResult = {
  asin: string
  status: 'ok' | 'unavailable' | 'blocked'
  reason: string
  audit: ImageAudit | null
}

/** One check as the service's DETAIL record carries it (`GET /audit/{id}`).
 *
 * ⚠ `status` here is RAW, and that is the one thing to know about this type.
 * When a main-image-only rule is evaluated against a secondary image, the
 * service changes `tier` to "advisory" and leaves `status` as "fail" — the
 * neutralisation to "measured" happens only when the compact payload is built.
 * So this array legitimately contains `{check_id: "white_background", status:
 * "fail", tier: "advisory"}` for a perfectly compliant lifestyle photo.
 *
 * NEVER render this array as findings. It is a lookup table: reason text for a
 * code that the compact payload has ALREADY declared a verdict, plus per-image
 * file facts. Enumerating it would put red FAILs on compliant images, which is
 * precisely the failure the compact payload exists to prevent — see the
 * docstring on ImageAuditCard.
 */
export type AuditCheckDetail = {
  check_id: string
  status: 'pass' | 'warn' | 'fail' | 'skipped'
  tier: 'rule_exact' | 'measured' | 'advisory' | 'model' | 'deferred'
  value: number | null
  rule: string
  reason: string
  detail: Record<string, unknown>
}

/** Per-image facts from the detail record. `orig_width`/`orig_height` are the
 * dimensions the audit actually measured — original, after EXIF rotation — so
 * they are the numbers a verdict like "92px" was computed from. A browser's
 * `naturalWidth` can disagree on a rotated JPEG, which is why these win. */
export type AuditImageDetail = {
  source: string
  is_main: boolean | null
  sha256: string
  orig_width: number
  orig_height: number
  format: string
  n_bytes: number
  downscale: number
  checks: AuditCheckDetail[]
  hashes: Record<string, number | string>
}

export type AuditDetail = {
  payload: ImageAudit
  images: AuditImageDetail[]
  duplicates: Record<string, unknown>
  group_mismatches: unknown[]
}

/** What the browser knows about a file it uploaded, and the service cannot:
 * the pixels. The service stores no image bytes, so a thumbnail can only ever
 * come from a local blob URL. */
export type PickedImageMeta = {
  name: string
  size: number
  type: string
  url: string
  width: number | null
  height: number | null
}

export type TraceStep =
  | { kind: 'node_started'; node: string; label: string; ts: number }
  | { kind: 'plan_ready'; query_type: string; plan: string[]; ts: number }
  | { kind: 'tool_call'; tool: string; args: Record<string, unknown>; ts: number }
  | {
      kind: 'tool_result'
      tool: string
      preview: string
      /** Structured payload, present only for `image_audit`.
       *
       *  This is the whole tool result — `{ asin, status, reason, audit }` —
       *  not the inner `audit` object. Keeping the wrapper is what lets the
       *  card render the `unavailable` and `blocked` states instead of only
       *  the happy path. */
      auditResult?: ImageAuditResult
      ts: number
    }
  | { kind: 'executor_thought'; content: string; ts: number }
  | { kind: 'replan'; reason: string; ts: number }
  | { kind: 'error'; message: string; ts: number }
  | { kind: 'done'; ts: number }
