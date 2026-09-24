import { describe, expect, it } from 'vitest'
import { switchHref } from '@/lib/product-nav'

describe('switchHref', () => {
  it('keeps you on the same per-product page for the new product', () => {
    for (const page of [
      '/dashboard',
      '/dashboard/reviews',
      '/dashboard/conversations',
      '/dashboard/compare',
      '/dashboard/brief',
      '/assistant',
      '/chat',
      '/agent',
    ]) {
      expect(switchHref(page, 'B075X8471B'), page).toBe(`${page}?asin=B075X8471B`)
    }
  })

  it('sends pages that are not about one product to the new product dashboard', () => {
    expect(switchHref('/dashboard/images', 'B075X8471B')).toBe('/dashboard?asin=B075X8471B')
    expect(switchHref('/dashboard/reports', 'B075X8471B')).toBe('/dashboard?asin=B075X8471B')
    expect(switchHref('/', 'B075X8471B')).toBe('/dashboard?asin=B075X8471B')
  })

  it('ignores a trailing slash', () => {
    expect(switchHref('/dashboard/brief/', 'B075X8471B')).toBe('/dashboard/brief?asin=B075X8471B')
  })
})
