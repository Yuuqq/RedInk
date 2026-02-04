export type SSEHandlers = Record<string, (data: any) => void>

/**
 * Consume a fetch() Response body as Server-Sent Events (SSE).
 *
 * Supports:
 * - multi-line `data:` (joined with '\n')
 * - chunk boundaries splitting lines/events
 * - optional `event:` type (defaults to 'message')
 */
export async function consumeSSE(response: Response, handlers: SSEHandlers) {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('无法读取响应流')

  const decoder = new TextDecoder()

  let buffer = ''
  let eventType = 'message'
  let dataLines: string[] = []

  const dispatch = () => {
    if (dataLines.length === 0) {
      eventType = 'message'
      return
    }

    const raw = dataLines.join('\n')
    dataLines = []

    let data: any = raw
    try {
      data = JSON.parse(raw)
    } catch {
      // keep raw string
    }

    const handler = handlers[eventType] || handlers['message']
    if (handler) handler(data)

    eventType = 'message'
  }

  const handleLine = (line: string) => {
    // Ignore comments
    if (line.startsWith(':')) return

    if (line === '') {
      dispatch()
      return
    }

    if (line.startsWith('event:')) {
      eventType = line.slice('event:'.length).trim() || 'message'
      return
    }

    if (line.startsWith('data:')) {
      // Keep spaces after "data:" per SSE spec
      const v = line.slice('data:'.length)
      dataLines.push(v.startsWith(' ') ? v.slice(1) : v)
      return
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // Process complete lines
    while (true) {
      const idx = buffer.indexOf('\n')
      if (idx === -1) break

      let line = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 1)
      if (line.endsWith('\r')) line = line.slice(0, -1)

      handleLine(line)
    }
  }

  // Flush last event if stream ends without a trailing blank line
  if (buffer.length > 0) {
    if (buffer.endsWith('\r')) buffer = buffer.slice(0, -1)
    handleLine(buffer)
  }
  dispatch()
}

