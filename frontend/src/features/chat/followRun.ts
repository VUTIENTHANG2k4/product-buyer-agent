import { apiUrl, toApiError } from '@/api/client'
import { isTerminal, parseAgentEvent, type AgentEvent } from './events'
import { SseParser } from './sse'

/** Thời gian chờ trước mỗi lần nối lại (docs/08 §4: tự nối lại 3 lần rồi mới dùng `GET /chat/{run_id}`). */
export const RECONNECT_DELAYS_MS: readonly number[] = [500, 1000, 2000]

export interface FollowOptions {
  signal: AbortSignal
  /** `id` của sự kiện cuối đã nhận, gửi ở header `Last-Event-ID` để máy chủ phát tiếp từ sau đó. */
  lastEventId: () => number | null
  onEvent: (id: number | null, event: AgentEvent) => void
  delaysMs?: readonly number[]
}

/** `terminal`: nhận được sự kiện kết thúc · `exhausted`: nối lại hết lần mà chưa xong. */
export type FollowResult = 'terminal' | 'exhausted'

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason)
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal.reason)
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

function parseId(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) return null
  return Number(raw)
}

/** Một lần kết nối: đọc luồng đến hết; `true` nếu đã thấy sự kiện kết thúc. */
async function readOnce(runId: string, options: FollowOptions): Promise<boolean> {
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  const last = options.lastEventId()
  if (last !== null) headers['Last-Event-ID'] = String(last)

  const response = await fetch(apiUrl(`chat/${encodeURIComponent(runId)}/events`), {
    headers,
    signal: options.signal,
  })
  if (!response.ok) throw await toApiError(response)
  if (!response.body) return false

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()
  // `SseParser` giữ `id` của sự kiện trước cho sự kiện không có dòng `id:` (đúng đặc tả). Máy chủ
  // không bao giờ dùng lại một id, nên id lặp lại ngay sau chính nó nghĩa là sự kiện này không có id
  // riêng: báo `null` để reducer không coi là bản trùng và bỏ sót sự kiện (kể cả `final`/`error`).
  let previousRawId: string | null = null
  const idOf = (message: { id: string | null }): number | null => {
    const fresh = message.id !== previousRawId
    previousRawId = message.id
    return fresh ? parseId(message.id) : null
  }
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      for (const message of parser.push(decoder.decode(value, { stream: true }))) {
        const event = parseAgentEvent(message.event, message.data)
        if (!event) continue
        options.onEvent(idOf(message), event)
        if (isTerminal(event)) return true
      }
    }
    for (const message of [...parser.push(decoder.decode()), ...parser.end()]) {
      const event = parseAgentEvent(message.event, message.data)
      if (!event) continue
      options.onEvent(idOf(message), event)
      if (isTerminal(event)) return true
    }
    return false
  } finally {
    void reader.cancel().catch(() => undefined)
  }
}

/**
 * Theo dõi một lượt chạy qua SSE (`fetch` + luồng, không dùng `EventSource` vì cần header
 * `Last-Event-ID` khi tự nối lại và huỷ bằng `AbortSignal`). Mất kết nối, 5xx hoặc luồng đóng khi
 * chưa có sự kiện kết thúc thì chờ rồi nối lại tối đa `delaysMs.length` lần. Lỗi 4xx (vd.
 * `RUN_NOT_FOUND`) và huỷ được ném ra ngay cho bên gọi.
 */
export async function followRun(runId: string, options: FollowOptions): Promise<FollowResult> {
  const delays = options.delaysMs ?? RECONNECT_DELAYS_MS
  for (let attempt = 0; attempt <= delays.length; attempt += 1) {
    if (attempt > 0) await sleep(delays[attempt - 1] as number, options.signal)
    try {
      if (await readOnce(runId, options)) return 'terminal'
    } catch (error) {
      if (options.signal.aborted) throw error
      const status = (error as { status?: unknown }).status
      if (typeof status === 'number' && status >= 400 && status < 500) throw error
      // Lỗi mạng, 5xx hoặc luồng hỏng giữa chừng: thử lại.
    }
  }
  return 'exhausted'
}
