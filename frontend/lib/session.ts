import { headers } from 'next/headers'
import { getAuth } from './auth'

/** The signed-in user's id, or null. Every /api/me/* handler calls this itself:
 *  a middleware check alone isn't trusted to gate data. */
export async function currentUserId(): Promise<string | null> {
  const session = await getAuth().api.getSession({ headers: await headers() })
  return session?.user?.id ?? null
}
