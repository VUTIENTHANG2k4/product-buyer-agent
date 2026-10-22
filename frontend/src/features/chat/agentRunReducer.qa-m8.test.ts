import type { Schemas } from '@/api/types'
import { sample } from '@/test/sse'
import {
  agentRunReducer,
  initialAgentRunState,
  type AgentRunAction,
  type AgentRunState,
} from './agentRunReducer'
import type { AgentEvent, FinalEvent } from './events'

const final = sample.final as FinalEvent
const toolStart = (callId: string): AgentEvent => ({
  name: 'tool_start',
  callId,
  tool: 'search_catalog',
  argsSummary: 'laptop',
})
const toolEnd = (callId: string, ok = true): AgentEvent => ({
  name: 'tool_end',
  callId,
  tool: 'search_catalog',
  ok,
  summary: ok ? 'xong' : 'lỗi',
  durationMs: 5,
})

function run(actions: AgentRunAction[], from: AgentRunState = initialAgentRunState): AgentRunState {
  return actions.reduce(agentRunReducer, from)
}

describe('agentRunReducer · biên (QA M8)', () => {
  it('lastEventId không lùi: id thấp hơn bị bỏ, id lớn hơn (nhảy cóc) được nhận', () => {
    const state = run([
      { type: 'event', id: 3, event: toolStart('a') },
      { type: 'event', id: 1, event: toolStart('b') },
      { type: 'event', id: 9, event: toolStart('c') },
    ])
    expect(state.tools.map((tool) => tool.callId)).toEqual(['a', 'c'])
    expect(state.lastEventId).toBe(9)
  })

  it('hai sự kiện khác loại cùng id: sự kiện sau bị coi là phát lại và bỏ', () => {
    const state = run([
      { type: 'event', id: 2, event: toolStart('a') },
      { type: 'event', id: 2, event: toolEnd('a') },
    ])
    expect(state.tools[0]?.status).toBe('running')
  })

  it('sự kiện không có id không làm đổi lastEventId đã có', () => {
    const state = run([
      { type: 'event', id: 4, event: toolStart('a') },
      { type: 'event', id: null, event: toolEnd('a') },
    ])
    expect(state.lastEventId).toBe(4)
    expect(state.tools[0]?.status).toBe('ok')
  })

  it('1000 lượt gọi tool vẫn được ghi đủ và giữ thứ tự', () => {
    const actions: AgentRunAction[] = []
    for (let i = 0; i < 1000; i += 1) {
      actions.push({ type: 'event', id: i * 2, event: toolStart(`c${i}`) })
      actions.push({ type: 'event', id: i * 2 + 1, event: toolEnd(`c${i}`, i % 2 === 0) })
    }
    const state = run(actions)
    expect(state.tools).toHaveLength(1000)
    expect(state.tools[999]).toMatchObject({ callId: 'c999', status: 'failed' })
    expect(state.lastEventId).toBe(1999)
  })

  it('snapshot có cả final và error: final thắng (lượt đã có câu trả lời)', () => {
    const status: Schemas['RunStatusResponse'] = {
      run_id: 'r',
      conversation_id: 1,
      status: 'succeeded',
      intent: null,
      final,
      error: { code: 'X', message: 'y' },
    }
    const state = run([{ type: 'snapshot', status }])
    expect(state.phase).toBe('done')
    expect(state.error).toBeNull()
  })

  it('snapshot đến giữa chừng giữ nguyên các tool đã nhận và lastEventId', () => {
    const status: Schemas['RunStatusResponse'] = {
      run_id: 'r',
      conversation_id: 1,
      status: 'running',
      intent: null,
    }
    const state = run([
      { type: 'event', id: 0, event: toolStart('a') },
      { type: 'snapshot', status },
    ])
    expect(state.phase).toBe('running')
    expect(state.tools).toHaveLength(1)
    expect(state.lastEventId).toBe(0)
  })

  it('sau reset, id 0 được nhận lại (không bị coi là trùng với lượt cũ)', () => {
    const state = run([
      { type: 'event', id: 0, event: toolStart('a') },
      { type: 'reset' },
      { type: 'event', id: 0, event: toolStart('b') },
    ])
    expect(state.tools.map((tool) => tool.callId)).toEqual(['b'])
  })
})
