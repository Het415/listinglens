import { pool } from '@/lib/db'
import { currentUserId } from '@/lib/session'
import { json, unauthorized } from '@/lib/route-helpers'
import { recentProducts } from '@/lib/saved'

export const dynamic = 'force-dynamic'

export async function GET() {
  const userId = await currentUserId()
  if (!userId) return unauthorized()
  return json({ products: await recentProducts(pool(), userId) })
}
