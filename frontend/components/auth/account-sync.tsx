'use client'

import { useEffect } from 'react'
import { useSession } from '@/lib/auth-client'
import { setSyncUser } from '@/components/assistant/assistantStore'

/** Tells the module-scoped chat store who is signed in, so it can mirror
 *  histories to the account. Mounted once, in the root layout. */
export function AccountSync() {
  const { data: session, isPending } = useSession()
  const userId = session?.user?.id ?? null

  useEffect(() => {
    if (!isPending) setSyncUser(userId)
  }, [userId, isPending])

  return null
}
