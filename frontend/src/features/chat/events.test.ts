import { sample } from '@/test/sse'
import { isTerminal, parseAgentEvent } from './events'

const json = JSON.stringify

describe('parseAgentEvent', () => {
  it('plan', () => {
    const event = parseAgentEvent('plan', json(sample.plan))
    expect(event).toMatchObject({ name: 'plan', steps: sample.plan.steps })
  })

  it('clarification', () => {
    expect(parseAgentEvent('clarification', json({ question: 'Bạn cần loại nào?' }))).toEqual({
      name: 'clarification',
      question: 'Bạn cần loại nào?',
    })
  })

  it('tool_start và tool_end đổi sang camelCase', () => {
    expect(parseAgentEvent('tool_start', json(sample.toolStart))).toEqual({
      name: 'tool_start',
      callId: 'c1',
      tool: 'search_catalog',
      argsSummary: 'laptop, ≤ 30.000.000 ₫',
    })
    expect(parseAgentEvent('tool_end', json(sample.toolEnd))).toEqual({
      name: 'tool_end',
      callId: 'c1',
      tool: 'search_catalog',
      ok: true,
      summary: 'Tìm thấy 7 sản phẩm',
      durationMs: 84,
    })
  })

  it('final giữ bảng, gợi ý và mốc dữ liệu; trường tùy chọn thiếu thì có giá trị mặc định', () => {
    const event = parseAgentEvent('final', json({ text: 'Xong', table: [] }))
    expect(event).toMatchObject({
      name: 'final',
      final: { text: 'Xong', table: [], live_items: [], suggestions: [], data_as_of: null },
    })
  })

  it('error', () => {
    expect(
      parseAgentEvent('error', json({ code: 'AGENT_STEP_LIMIT', message: 'Hết bước' })),
    ).toEqual({ name: 'error', error: { code: 'AGENT_STEP_LIMIT', message: 'Hết bước' } })
  })

  it.each([
    ['plan', json({ steps: [] })],
    ['plan', json({ intent: {}, steps: [1] })],
    ['clarification', json({})],
    ['tool_start', json({ tool: 'x' })],
    ['tool_end', json({ call_id: 1, tool: 'x' })],
    ['final', json({ text: 'x' })],
    ['final', json({ text: 1, table: [] })],
    ['error', json({ code: 'X' })],
    ['plan', 'không phải json'],
    ['plan', json([1, 2])],
    ['plan', json(null)],
    ['unknown_event', json({})],
  ])('%s với dữ liệu hỏng %s → null, không ném lỗi', (name, raw) => {
    expect(parseAgentEvent(name, raw)).toBeNull()
  })
})

describe('isTerminal', () => {
  it('chỉ final, error và clarification kết thúc lượt', () => {
    const names = ['plan', 'tool_start', 'tool_end', 'final', 'error', 'clarification'] as const
    const terminal = names.filter((name) => {
      const raw = {
        plan: sample.plan,
        tool_start: sample.toolStart,
        tool_end: sample.toolEnd,
        final: sample.final,
        error: { code: 'X', message: 'm' },
        clarification: { question: 'q' },
      }[name]
      const event = parseAgentEvent(name, json(raw))
      return event !== null && isTerminal(event)
    })
    expect(terminal).toEqual(['final', 'error', 'clarification'])
  })
})
