/**
 * Public demo product used as the default ASIN when a user lands on
 * `/dashboard` (or `/dashboard/reviews`, or `/assistant`) without specifying
 * `?asin=` in the URL.
 *
 * Picking a single source of truth for this avoids drift between pages and
 * makes the demo-mode banner detection (`!searchParams.get('asin')`) simple
 * to reason about.
 *
 * The product is a TOZO T10 Bluetooth Earbuds listing — chosen because it has
 * a healthy mix of 1-, 3-, and 5-star reviews, so every dashboard widget
 * (sentiment, topics, return risk) has interesting data to show on first load.
 */
export const DEMO_ASIN = 'B08XPWDSWW'
export const DEMO_PRODUCT_NAME = 'TOZO T10 Bluetooth Earbuds'
