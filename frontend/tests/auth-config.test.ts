// The account-linking rule is a security decision; pin it so a config edit
// can't quietly loosen it. (The linking flow itself needs real OAuth and is
// checked by hand — see the PR description.)

import { beforeAll, describe, expect, it } from 'vitest'

beforeAll(() => {
  // authOptions() builds a pg Pool, which doesn't connect until first query.
  process.env.DATABASE_URL ??= 'postgres://unused@localhost:1/unused'
  process.env.GOOGLE_CLIENT_ID = 'g-id'
  process.env.GOOGLE_CLIENT_SECRET = 'g-secret'
  process.env.GITHUB_CLIENT_ID = 'gh-id'
  process.env.GITHUB_CLIENT_SECRET = 'gh-secret'
})

describe('authOptions', () => {
  it('links Google and GitHub only on verified emails, trusting no provider by name', async () => {
    const { authOptions } = await import('@/lib/auth')
    const linking = authOptions().account?.accountLinking
    expect(linking?.enabled).toBe(true)
    expect(linking?.requireLocalEmailVerified).toBe(true)
    expect(linking?.trustedProviders).toBeUndefined()
    expect(linking?.disableImplicitLinking).not.toBe(true)
  })

  it('offers both providers and lets users delete their account', async () => {
    const { authOptions } = await import('@/lib/auth')
    const opts = authOptions()
    expect(Object.keys(opts.socialProviders ?? {}).sort()).toEqual(['github', 'google'])
    expect(opts.user?.deleteUser?.enabled).toBe(true)
  })

  it('skips a provider whose credentials are missing', async () => {
    const { authOptions } = await import('@/lib/auth')
    const saved = process.env.GITHUB_CLIENT_SECRET
    delete process.env.GITHUB_CLIENT_SECRET
    try {
      expect(Object.keys(authOptions().socialProviders ?? {})).toEqual(['google'])
    } finally {
      process.env.GITHUB_CLIENT_SECRET = saved
    }
  })
})
