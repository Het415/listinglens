import { pool } from '@/lib/db'
import { currentUserId } from '@/lib/session'
import { json, readJson, unauthorized } from '@/lib/route-helpers'
import { createReport, listReports, MAX_REPORTS_PER_USER, ReportInput } from '@/lib/saved'

export const dynamic = 'force-dynamic'

export async function GET() {
  const userId = await currentUserId()
  if (!userId) return unauthorized()
  return json({ reports: await listReports(pool(), userId) })
}

export async function POST(request: Request) {
  const userId = await currentUserId()
  if (!userId) return unauthorized()

  const body = await readJson(request)
  if (!body.ok) return body.response
  const parsed = ReportInput.safeParse(body.value)
  if (!parsed.success) return json({ error: 'invalid report' }, 422)

  const id = await createReport(pool(), userId, parsed.data)
  if (!id) {
    return json(
      { error: `You have ${MAX_REPORTS_PER_USER} saved reports. Delete some before saving more.` },
      409,
    )
  }
  return json({ id }, 201)
}
