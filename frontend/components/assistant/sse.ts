export async function* readSSE(
  response: Response,
): AsyncGenerator<{ event: string; data: any }> {
  const reader = response.body?.getReader()
  if (!reader) return

  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) return
    buf += decoder.decode(value, { stream: true })

    let sepIdx: number
    while ((sepIdx = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, sepIdx)
      buf = buf.slice(sepIdx + 2)

      let eventName = 'message'
      let dataStr = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
      }
      if (dataStr) {
        try {
          yield { event: eventName, data: JSON.parse(dataStr) }
        } catch {
          yield { event: eventName, data: { raw: dataStr } }
        }
      }
    }
  }
}
