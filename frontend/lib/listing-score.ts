/**
 * The Overall Listing Score (0–100), read from the API's `risk.listing_score`.
 *
 * It used to be derived here as (1 - risk_score) * 100. risk_score is the
 * return-risk model's probability, which sits near 0 or 1, so that showed
 * 100/100 on every product. The API now computes the score from the composite
 * the model's label is built on (`listing_score` in src/fusion.py).
 *
 * null when the payload has none (an API older than the field), so callers
 * show a dash instead of a made-up number.
 */
export function listingScore(risk?: { listing_score?: number } | null): number | null {
  const s = risk?.listing_score
  return typeof s === 'number' && Number.isFinite(s) ? s : null
}
