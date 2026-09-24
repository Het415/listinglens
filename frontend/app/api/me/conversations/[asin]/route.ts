import { pool } from '@/lib/db'
import { currentUserId } from '@/lib/session'
import { json, notFound, readJson, unauthorized } from '@/lib/route-helpers'
import {
  ASIN_RE,
  ConversationInput,
  deleteConversation,
  getConversation,
  putConversation,
} from '@/lib/saved'

export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ asin: string }> }

async function resolve(ctx: Ctx): Promise<{ userId: string; asin: string } | Response> {
  const userId = await currentUserId()
  if (!userId) return unauthorized()
  const { asin } = await ctx.params
  if (!ASIN_RE.test(asin)) return notFound()
  return { userId, asin }
}

export async function GET(_request: Request, ctx: Ctx) {
  const r = await resolve(ctx)
  if (r instanceof Response) return r
  const messages = await getConversation(pool(), r.userId, r.asin)
  return json({ messages: messages ?? [] })
}

export async function PUT(request: Request, ctx: Ctx) {
  const r = await resolve(ctx)
  if (r instanceof Response) return r
  const body = await readJson(request)
  if (!body.ok) return body.response
  const parsed = ConversationInput.safeParse(body.value)
  if (!parsed.success) return json({ error: 'invalid conversation' }, 422)
  await putConversation(pool(), r.userId, r.asin, parsed.data.messages)
  return new Response(null, { status: 204 })
}

export async function DELETE(_request: Request, ctx: Ctx) {
  const r = await resolve(ctx)
  if (r instanceof Response) return r
  await deleteConversation(pool(), r.userId, r.asin)
  return new Response(null, { status: 204 })
}
