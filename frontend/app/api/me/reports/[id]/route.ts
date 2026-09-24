import { pool } from '@/lib/db'
import { currentUserId } from '@/lib/session'
import { json, notFound, unauthorized } from '@/lib/route-helpers'
import { deleteReport, getReport } from '@/lib/saved'

export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ id: string }> }

export async function GET(_request: Request, { params }: Ctx) {
  const userId = await currentUserId()
  if (!userId) return unauthorized()
  const report = await getReport(pool(), userId, (await params).id)
  return report ? json({ report }) : notFound()
}

export async function DELETE(_request: Request, { params }: Ctx) {
  const userId = await currentUserId()
  if (!userId) return unauthorized()
  const deleted = await deleteReport(pool(), userId, (await params).id)
  return deleted ? new Response(null, { status: 204 }) : notFound()
}
