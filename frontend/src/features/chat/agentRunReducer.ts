import type { Schemas } from '@/api/types'
import type { AgentEvent, ErrorEvent, FinalEvent, QueryIntent } from './events'

export interface ToolStep {
  callId: string
  tool: string
  argsSummary: string
  status: 'running' | 'ok' | 'failed'
  summary?: string
  durationMs?: number
}

/** `connecting`: chưa nhận gì · `running`: đang nhận · phần còn lại là kết thúc lượt. */
export type RunPhase = 'connecting' | 'running' | 'done' | 'clarification' | 'error'

export interface AgentRunState {
  phase: RunPhase
  intent: QueryIntent | null
  steps: string[]
  tools: ToolStep[]
  final: FinalEvent | null
  clarification: string | null
  error: ErrorEvent | null
  /** `id` của sự kiện cuối đã xử lý, gửi lại ở header `Last-Event-ID` khi nối lại. */
  lastEventId: number | null
}

export type AgentRunAction =
  | { type: 'event'; id: number | null; event: AgentEvent }
  | { type: 'snapshot'; status: Schemas['RunStatusResponse'] }
  | { type: 'fail'; error: ErrorEvent }
  | { type: 'reset' }

export const CONNECTION_LOST = 'CONNECTION_LOST'

export const initialAgentRunState: AgentRunState = {
  phase: 'connecting',
  intent: null,
  steps: [],
  tools: [],
  final: null,
  clarification: null,
  error: null,
  lastEventId: null,
}

export function isFinished(phase: RunPhase): boolean {
  return phase === 'done' || phase === 'clarification' || phase === 'error'
}

function applyEvent(state: AgentRunState, event: AgentEvent): AgentRunState {
  switch (event.name) {
    case 'plan':
      return { ...state, phase: 'running', intent: event.intent, steps: event.steps }
    case 'tool_start':
      return {
        ...state,
        phase: 'running',
        tools: [
          ...state.tools.filter((tool) => tool.callId !== event.callId),
          {
            callId: event.callId,
            tool: event.tool,
            argsSummary: event.argsSummary,
            status: 'running',
          },
        ],
      }
    case 'tool_end': {
      const finished: ToolStep = {
        callId: event.callId,
        tool: event.tool,
        argsSummary: '',
        status: event.ok ? 'ok' : 'failed',
        summary: event.summary,
        durationMs: event.durationMs,
      }
      const known = state.tools.some((tool) => tool.callId === event.callId)
      return {
        ...state,
        phase: 'running',
        tools: known
          ? state.tools.map((tool) =>
              tool.callId === event.callId
                ? { ...tool, ...finished, argsSummary: tool.argsSummary }
                : tool,
            )
          : [...state.tools, finished],
      }
    }
    case 'clarification':
      return { ...state, phase: 'clarification', clarification: event.question }
    case 'final':
      return { ...state, phase: 'done', final: event.final }
    case 'error':
      return { ...state, phase: 'error', error: event.error }
  }
}

/** Gộp sự kiện SSE (bỏ sự kiện trùng `id` khi phát lại sau lúc nối lại) và ảnh chụp từ `GET /chat/{run_id}`. */
export function agentRunReducer(state: AgentRunState, action: AgentRunAction): AgentRunState {
  switch (action.type) {
    case 'reset':
      return initialAgentRunState
    case 'event': {
      if (isFinished(state.phase)) return state
      if (action.id !== null && state.lastEventId !== null && action.id <= state.lastEventId) {
        return state
      }
      const next = applyEvent(state, action.event)
      return action.id === null ? next : { ...next, lastEventId: action.id }
    }
    case 'fail':
      return isFinished(state.phase) ? state : { ...state, phase: 'error', error: action.error }
    case 'snapshot': {
      if (isFinished(state.phase)) return state
      const { status } = action
      const base: AgentRunState = {
        ...state,
        intent: status.intent ?? state.intent,
        steps: state.steps.length > 0 ? state.steps : (status.intent?.plan_steps ?? []),
      }
      if (status.final) return { ...base, phase: 'done', final: status.final }
      if (status.clarification) {
        return { ...base, phase: 'clarification', clarification: status.clarification }
      }
      if (status.error) return { ...base, phase: 'error', error: status.error }
      return base
    }
  }
}
