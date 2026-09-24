'use client'

import { createAuthClient } from 'better-auth/react'

// Same-origin: the auth routes live at /api/auth/* on this Next.js app.
export const authClient = createAuthClient()

export const { signIn, signOut, useSession, deleteUser } = authClient
