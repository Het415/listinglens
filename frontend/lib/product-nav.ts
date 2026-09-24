// Where the product switcher sends you. Pages that are about one product keep
// you on the same page for the new one (brief → brief); pages that aren't
// (Image Audit, My Reports) have nothing to switch, so you land on that
// product's dashboard.

const PER_PRODUCT_PAGES = [
  '/dashboard',
  '/dashboard/reviews',
  '/dashboard/conversations',
  '/dashboard/compare',
  '/dashboard/brief',
  '/assistant',
  '/chat',
  '/agent',
]

export function switchHref(pathname: string, asin: string): string {
  const path = pathname.replace(/\/+$/, '') || '/'
  const target = PER_PRODUCT_PAGES.includes(path) ? path : '/dashboard'
  // Only ?asin= carries over. Other params belong to the old product (?q= on
  // the assistant would re-ask the old question, ?audit= is one product's).
  return `${target}?asin=${encodeURIComponent(asin)}`
}
