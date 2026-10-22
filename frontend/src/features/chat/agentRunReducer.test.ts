import { agentRunReducer, initialAgentRunState, type AgentRunState } from './agentRunReducer'
import type { AgentEvent } from './events'

const plan: AgentEvent = {
  name: 'plan',
  intent: { tier: 1, category: 'laptop' } as never,
  steps: ['Tìm laptop', 'Lọc giá'],
}
const start: AgentEvent = {
  name: 'tool_start',
  callId: 'c1',
  tool: 'search_catalog',
  argsSummary: 'laptop',
}
const end: AgentEvent = {
  name: 'tool_end',
  callId: 'c1',
  tool: 'search_catalog',
  ok: true,
  summary: 'Tìm thấy 3 sản phẩm',
  durationMs: 12,
}
const final: AgentEvent = {
  name: 'final',
  final: { text: 'Xong', table: [], live_items: [], suggestions: [], data_as_of: null },
}

function run(actions: Parameters<typeof agentRunReducer>[1][]): AgentRunState {
  return actions.reduce(agentRunReducer, initialAgentRunState)
}
const ev = (event: AgentEvent, id: number | null = null) => ({ type: 'event' as const, id, event })

describe('agentRunReducer · sự kiện', () => {
  it('bắt đầu ở connecting, plan chuyển sang running và lưu các bước', () => {
    expect(initialAgentRunState.phase).toBe('connecting')
    const state = run([ev(plan, 0)])
    expect(state).toMatchObject({
      phase: 'running',
      steps: ['Tìm laptop', 'Lọc giá'],
      lastEventId: 0,
    })
  })

  it('tool_start thêm một dòng đang chạy, tool_end chốt trạng thái và giữ tóm tắt tham số', () => {
    const running = run([ev(plan, 0), ev(start, 1)])
    expect(running.tools).toEqual([
      { callId: 'c1', tool: 'search_catalog', argsSummary: 'laptop', status: 'running' },
    ])
    const done = run([ev(plan, 0), ev(start, 1), ev(end, 2)])
    expect(done.tools).toEqual([
      {
        callId: 'c1',
        tool: 'search_catalog',
        argsSummary: 'laptop',
        status: 'ok',
        summary: 'Tìm thấy 3 sản phẩm',
        durationMs: 12,
      },
    ])
  })

  it('tool_end có ok=false đánh dấu failed; tool_end không có tool_start vẫn được ghi', () => {
    const failed = run([ev({ ...end, ok: false, summary: 'Lỗi' }, 1)])
    expect(failed.tools[0]).toMatchObject({ status: 'failed', summary: 'Lỗi' })
  })

  it('final kết thúc lượt, clarification và error cũng vậy', () => {
    expect(run([ev(plan, 0), ev(final, 1)])).toMatchObject({
      phase: 'done',
      final: { text: 'Xong' },
    })
    expect(run([ev({ name: 'clarification', question: 'Loại nào?' }, 1)])).toMatchObject({
      phase: 'clarification',
      clarification: 'Loại nào?',
    })
    expect(run([ev({ name: 'error', error: { code: 'X', message: 'lỗi' } }, 1)])).toMatchObject({
      phase: 'error',
      error: { code: 'X', message: 'lỗi' },
    })
  })

  it('bỏ sự kiện có id đã xử lý (phát lại sau khi nối lại) và sự kiện đến sau khi lượt đã xong', () => {
    const state = run([ev(plan, 0), ev(start, 1), ev(plan, 0), ev(start, 1), ev(end, 2)])
    expect(state.tools).toHaveLength(1)
    expect(state.lastEventId).toBe(2)

    const after = run([ev(final, 3), ev(start, 4)])
    expect(after.phase).toBe('done')
    expect(after.tools).toEqual([])
  })

  it('sự kiện không có id luôn được xử lý', () => {
    expect(run([ev(plan), ev(start)]).tools).toHaveLength(1)
  })

  it('reset về trạng thái đầu', () => {
    expect(run([ev(plan, 0), { type: 'reset' }])).toEqual(initialAgentRunState)
  })
})

describe('agentRunReducer · fail và snapshot', () => {
  const lost = { code: 'CONNECTION_LOST', message: 'Mất kết nối' }

  it('fail đặt trạng thái lỗi nhưng không đè lượt đã xong', () => {
    expect(run([{ type: 'fail', error: lost }])).toMatchObject({ phase: 'error', error: lost })
    expect(run([ev(final, 1), { type: 'fail', error: lost }]).phase).toBe('done')
  })

  const status = (over: Record<string, unknown>) => ({
    type: 'snapshot' as const,
    status: {
      run_id: 'r',
      conversation_id: 1,
      status: 'succeeded',
      intent: null,
      ...over,
    } as never,
  })

  it('snapshot có final → done; có clarification → clarification; có error → error', () => {
    const finalBody = { text: 'T', table: [], live_items: [], suggestions: [], data_as_of: null }
    expect(run([status({ final: finalBody })])).toMatchObject({ phase: 'done', final: finalBody })
    expect(run([status({ clarification: 'Hỏi gì?' })])).toMatchObject({
      phase: 'clarification',
      clarification: 'Hỏi gì?',
    })
    expect(run([status({ error: { code: 'E', message: 'm' } })]).phase).toBe('error')
  })

  it('snapshot lấy bước kế hoạch từ intent khi chưa nhận sự kiện plan', () => {
    const state = run([status({ status: 'running', intent: { plan_steps: ['A', 'B'] } })])
    expect(state).toMatchObject({ phase: 'connecting', steps: ['A', 'B'] })
  })

  it('snapshot không đè lượt đã xong', () => {
    expect(run([ev(final, 1), status({ error: { code: 'E', message: 'm' } })]).phase).toBe('done')
  })
})
