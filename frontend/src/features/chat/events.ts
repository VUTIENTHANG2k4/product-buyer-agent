import type { Schemas } from '@/api/types'

/**
 * Sự kiện tiến trình agent (docs/05 §6). OpenAPI chỉ mô tả `final` và `error`, nên các sự kiện còn
 * lại khai báo ở đây và được kiểm bằng `parseAgentEvent` (dữ liệu từ mạng là `unknown`).
 */
export type QueryIntent = Schemas['QueryIntent']
export type FinalEvent = Schemas['FinalEvent']
export type ErrorEvent = Schemas['ErrorEvent']

export type AgentEvent =
  | { name: 'plan'; intent: QueryIntent; steps: string[] }
  | { name: 'clarification'; question: string }
  | { name: 'tool_start'; callId: string; tool: string; argsSummary: string }
  | {
      name: 'tool_end'
      callId: string
      tool: string
      ok: boolean
      summary: string
      durationMs: number
    }
  | { name: 'final'; final: FinalEvent }
  | { name: 'error'; error: ErrorEvent }

/** Sự kiện kết thúc lượt: sau đó máy chủ đóng luồng. */
export function isTerminal(event: AgentEvent): boolean {
  return event.name === 'final' || event.name === 'error' || event.name === 'clarification'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

/** Đọc một sự kiện SSE; tên lạ hoặc dữ liệu sai hình dạng trả `null` (bỏ qua, không làm vỡ lượt). */
export function parseAgentEvent(name: string, raw: string): AgentEvent | null {
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(data)) return null

  switch (name) {
    case 'plan':
      if (!isRecord(data.intent) || !isStringArray(data.steps)) return null
      return { name, intent: data.intent as QueryIntent, steps: data.steps }
    case 'clarification':
      return typeof data.question === 'string' ? { name, question: data.question } : null
    case 'tool_start':
      if (typeof data.call_id !== 'string' || typeof data.tool !== 'string') return null
      return {
        name,
        callId: data.call_id,
        tool: data.tool,
        argsSummary: typeof data.args_summary === 'string' ? data.args_summary : '',
      }
    case 'tool_end':
      if (typeof data.call_id !== 'string' || typeof data.tool !== 'string') return null
      return {
        name,
        callId: data.call_id,
        tool: data.tool,
        ok: data.ok !== false,
        summary: typeof data.summary === 'string' ? data.summary : '',
        durationMs: typeof data.duration_ms === 'number' ? data.duration_ms : 0,
      }
    case 'final':
      if (typeof data.text !== 'string' || !Array.isArray(data.table)) return null
      return {
        name,
        final: {
          text: data.text,
          table: data.table as FinalEvent['table'],
          live_items: Array.isArray(data.live_items)
            ? (data.live_items as FinalEvent['live_items'])
            : [],
          suggestions: isStringArray(data.suggestions) ? data.suggestions : [],
          data_as_of: typeof data.data_as_of === 'string' ? data.data_as_of : null,
        },
      }
    case 'error':
      if (typeof data.code !== 'string' || typeof data.message !== 'string') return null
      return { name, error: { code: data.code, message: data.message } }
    default:
      return null
  }
}
