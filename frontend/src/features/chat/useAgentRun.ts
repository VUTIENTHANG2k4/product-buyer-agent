import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { apiFetch, ApiError } from '@/api/client'
import type { ResponseBody } from '@/api/types'
import { strings } from '@/lib/strings'
import {
  agentRunReducer,
  CONNECTION_LOST,
  initialAgentRunState,
  type AgentRunState,
} from './agentRunReducer'
import { followRun } from './followRun'

type RunStatus = ResponseBody<'/api/chat/{run_id}', 'get'>

interface Options {
  /** Thời gian chờ giữa các lần nối lại; test đặt `[0, 0, 0]`. */
  reconnectDelaysMs?: readonly number[]
}

/**
 * Theo dõi một lượt chạy của agent: SSE, tự nối lại 3 lần, rồi lấy kết quả cuối bằng
 * `GET /chat/{run_id}` (docs/08 §4). Một hook ứng với một lượt: đổi `runId` thì dựng lại component
 * bằng `key={runId}` để trạng thái bắt đầu mới. `reconnect` dùng sau lỗi mất kết nối.
 */
export function useAgentRun(
  runId: string | null,
  { reconnectDelaysMs }: Options = {},
): { state: AgentRunState; reconnect: () => void } {
  const [state, dispatch] = useReducer(agentRunReducer, initialAgentRunState)
  const [session, setSession] = useState(0)
  const lastEventId = useRef<number | null>(null)
  const delays = useRef(reconnectDelaysMs)

  useEffect(() => {
    if (runId === null) return
    const controller = new AbortController()

    async function run(id: string) {
      try {
        const result = await followRun(id, {
          signal: controller.signal,
          lastEventId: () => lastEventId.current,
          onEvent: (eventId, event) => {
            // Cập nhật ngay để lần nối lại sau gửi đúng `Last-Event-ID`, không đợi lượt render.
            if (eventId !== null) lastEventId.current = eventId
            dispatch({ type: 'event', id: eventId, event })
          },
          delaysMs: delays.current,
        })
        if (result === 'terminal') return
        const status = await apiFetch<RunStatus>(`chat/${encodeURIComponent(id)}`, {
          signal: controller.signal,
        })
        dispatch({ type: 'snapshot', status })
        // Lượt vẫn `running` trên máy chủ mà ta không nhận được gì: báo mất kết nối để người dùng thử lại.
        dispatch({
          type: 'fail',
          error: { code: CONNECTION_LOST, message: strings.chat.connectionLost },
        })
      } catch (error) {
        if (controller.signal.aborted) return
        const message = error instanceof ApiError ? error.message : strings.errors.unknown
        const code = error instanceof ApiError ? error.code : 'INTERNAL_ERROR'
        dispatch({ type: 'fail', error: { code, message } })
      }
    }

    void run(runId)
    return () => controller.abort()
  }, [runId, session])

  const reconnect = useCallback(() => {
    lastEventId.current = null
    dispatch({ type: 'reset' })
    setSession((value) => value + 1)
  }, [])

  return { state, reconnect }
}
