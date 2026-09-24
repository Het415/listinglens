import { describe, expect, it } from 'vitest'
import { savedView } from '@/lib/saved'

const rec = { decision: 'go', confidence: 0.8, summary: 'ok', reasoning_steps: [], evidence: [], risks: [], suggested_next_actions: [] }

describe('savedView', () => {
  it('renders a current copilot report as a RecommendationCard', () => {
    expect(savedView({ kind: 'copilot', payload: { schema_version: 1, data: rec } }).type).toBe('copilot')
  })

  it('renders a current brief as a BriefView', () => {
    const brief = { asin: 'B08XPWDSWW', metrics: {}, brief: { headline: 'h' } }
    expect(savedView({ kind: 'brief', payload: { schema_version: 1, data: brief } }).type).toBe('brief')
  })

  it('falls back for an unknown schema_version instead of trusting the shape', () => {
    expect(savedView({ kind: 'copilot', payload: { schema_version: 2, data: rec } }).type).toBe('fallback')
    expect(savedView({ kind: 'copilot', payload: { data: rec } }).type).toBe('fallback')
  })

  it('falls back when the data no longer matches the kind', () => {
    expect(savedView({ kind: 'copilot', payload: { schema_version: 1, data: { headline: 'x' } } }).type).toBe('fallback')
    expect(savedView({ kind: 'brief', payload: { schema_version: 1, data: rec } }).type).toBe('fallback')
    expect(savedView({ kind: 'copilot', payload: { schema_version: 1, data: null } }).type).toBe('fallback')
  })
})
