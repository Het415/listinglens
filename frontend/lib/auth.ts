import { betterAuth, type BetterAuthOptions } from 'better-auth'
import { nextCookies } from 'better-auth/next-js'
import { pool } from './db'

// Sign-in is optional: anyone can run an analysis, and an account only exists
// so a seller can keep reports and chats across sessions.

/** Exported so the config test can assert the security-relevant settings
 *  without a database. */
export function authOptions(): BetterAuthOptions {
  const socialProviders: NonNullable<BetterAuthOptions['socialProviders']> = {}
  // Each provider is registered only when its credentials exist, so local dev
  // works with just one of them configured.
  if (process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET) {
    socialProviders.google = {
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
      prompt: 'select_account',
    }
  }
  if (process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET) {
    socialProviders.github = {
      clientId: process.env.GITHUB_CLIENT_ID,
      clientSecret: process.env.GITHUB_CLIENT_SECRET,
    }
  }

  return {
    appName: 'ListingLens',
    baseURL: process.env.BETTER_AUTH_URL,
    secret: process.env.BETTER_AUTH_SECRET,
    database: pool(),
    socialProviders,
    account: {
      // Google and GitHub returning the same email end up as ONE user, but
      // only when the incoming provider says the email is verified and the
      // existing user's email is verified too (Better Auth's defaults, kept on
      // purpose). No `trustedProviders`: trusting GitHub by name would let an
      // unverified GitHub email take over a Google-created account.
      accountLinking: { enabled: true, requireLocalEmailVerified: true },
    },
    session: {
      // Signed cookie cache: most session reads skip the database.
      cookieCache: { enabled: true, maxAge: 5 * 60 },
    },
    // Rows in saved_reports / conversations reference "user"(id) ON DELETE
    // CASCADE, so deleting the account deletes everything saved under it.
    user: { deleteUser: { enabled: true } },
    plugins: [nextCookies()],
  }
}

type Auth = ReturnType<typeof betterAuth>

// Built on first use, not at import: `next build` imports route modules while
// collecting page data, and CI has no DATABASE_URL.
const g = globalThis as unknown as { __llAuth?: Auth }

export function getAuth(): Auth {
  if (!g.__llAuth) g.__llAuth = betterAuth(authOptions())
  return g.__llAuth
}
