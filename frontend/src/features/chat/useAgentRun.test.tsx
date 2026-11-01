import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { server } from '@/mocks/server'
import { sample, sseFrame, sseResponse } from '@/test/sse'
import { useAgentRun } from './useAgentRun'

const RUN = '3f1c2d4e-0000-4000-8000-000000000001'
const events = () => apiUrl(`chat/${RUN}/events`)
const status = () => apiUrl(`chat/${RUN}`)
const FAST = { reconnectDelaysMs: [0, 0, 0] }

const planFrame = sseFrame('plan', sample.plan, 0)
const startFrame = sseFrame('tool_start', sample.toolStart, 1)
const endFrame = sseFrame('tool_end', sample.toolEnd, 2)
const finalFrame = sseFrame('final', sample.final, 3)

function render(runId: string | null = RUN) {
  return renderHook(() => useAgentRun(runId, FAST))
}

describe('useAgentRun · luồng SSE', () => {
  it('đi từ connecting → running → done và giữ kế hoạch, từng tool và câu trả lời', async () => {
    server.use(http.get(events(), () => sseResponse([planFrame, startFrame, endFrame, finalFrame])))
    const { result } = render()
    expect(result.current.state.phase).toBe('connecting')

    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    const { state } = result.current
    expect(state.steps).toEqual(sample.plan.steps)
    expect(state.tools).toEqual([
      expect.objectContaining({ callId: 'c1', status: 'ok', summary: 'Tìm thấy 7 sản phẩm' }),
    ])
    expect(state.final?.text).toBe('Có 7 laptop phù hợp.')
    expect(state.lastEventId).toBe(3)
  })

  it('ghép đúng khi khung SSE và ký tự tiếng Việt bị cắt giữa các lần đọc', async () => {
    const whole = planFrame + finalFrame
    const bytes = new TextEncoder().encode(whole)
    const middle = Math.floor(bytes.length / 2)
    // Cắt theo byte có thể rơi giữa một ký tự nhiều byte; TextDecoder phải giữ phần dở.
    const chunks = [bytes.slice(0, middle), bytes.slice(middle)]
    server.use(
      http.get(
        events(),
        () =>
          new HttpResponse(
            new ReadableStream({
              start(controller) {
                for (const chunk of chunks) controller.enqueue(chunk)
                controller.close()
              },
            }),
            { headers: { 'Content-Type': 'text/event-stream' } },
          ),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.steps).toEqual(sample.plan.steps)
  })

  it('bỏ qua sự kiện lạ hoặc hỏng, không làm vỡ lượt', async () => {
    server.use(
      http.get(events(), () =>
        sseResponse([
          'event: mystery\ndata: {}\n\n',
          'event: plan\ndata: không phải json\n\n',
          ': keep-alive\n\n',
          planFrame,
          finalFrame,
        ]),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.steps).toEqual(sample.plan.steps)
  })

  it('clarification kết thúc lượt và không kết nối lại', async () => {
    let calls = 0
    server.use(
      http.get(events(), () => {
        calls += 1
        return sseResponse([planFrame, sseFrame('clarification', { question: 'Loại nào?' }, 1)])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('clarification'))
    expect(result.current.state.clarification).toBe('Loại nào?')
    expect(calls).toBe(1)
  })

  it('sự kiện error (vd. AGENT_HALLUCINATION) → phase error với thông điệp của máy chủ', async () => {
    server.use(
      http.get(events(), () =>
        sseResponse([
          planFrame,
          sseFrame('error', { code: 'AGENT_HALLUCINATION', message: 'Không tìm được sản phẩm' }, 1),
        ]),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('error'))
    expect(result.current.state.error).toEqual({
      code: 'AGENT_HALLUCINATION',
      message: 'Không tìm được sản phẩm',
    })
  })

  it('runId null: không gọi mạng', () => {
    const { result } = render(null)
    expect(result.current.state.phase).toBe('connecting')
  })
})

describe('useAgentRun · nối lại và dự phòng', () => {
  it('mất kết nối giữa chừng: nối lại với Last-Event-ID và không nhân đôi sự kiện đã nhận', async () => {
    const headers: (string | null)[] = []
    server.use(
      http.get(events(), ({ request }) => {
        headers.push(request.headers.get('Last-Event-ID'))
        if (headers.length === 1) return sseResponse([planFrame + startFrame], 'error')
        // Máy chủ phát lại từ sau id 1, nhưng cố tình gửi cả id 1 để kiểm tra việc bỏ trùng.
        return sseResponse([startFrame, endFrame, finalFrame])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))

    expect(headers).toEqual([null, '1'])
    expect(result.current.state.tools).toHaveLength(1)
    expect(result.current.state.tools[0]?.status).toBe('ok')
  })

  it('luồng đóng sớm khi chưa có sự kiện kết thúc cũng được nối lại', async () => {
    let calls = 0
    server.use(
      http.get(events(), () => {
        calls += 1
        return calls === 1 ? sseResponse([planFrame]) : sseResponse([finalFrame])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(calls).toBe(2)
  })

  it('lỗi 5xx rồi thành công: thử lại', async () => {
    let calls = 0
    server.use(
      http.get(events(), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { error: { code: 'INTERNAL_ERROR', message: 'x', details: {} } },
              { status: 500 },
            )
          : sseResponse([planFrame, finalFrame])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(calls).toBe(2)
  })

  it('nối lại 3 lần vẫn lỗi thì lấy kết quả cuối bằng GET /chat/{run_id}', async () => {
    let sse = 0
    server.use(
      http.get(events(), () => {
        sse += 1
        return HttpResponse.error()
      }),
      http.get(status(), () =>
        HttpResponse.json({
          run_id: RUN,
          conversation_id: 1,
          status: 'succeeded',
          intent: null,
          final: sample.final,
        }),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(sse).toBe(4) // 1 lần đầu + 3 lần nối lại
    expect(result.current.state.final?.suggestions).toEqual(sample.final.suggestions)
  })

  it('dự phòng gặp lượt vẫn đang chạy → lỗi mất kết nối; reconnect() nối lại từ đầu', async () => {
    let phase: 'down' | 'up' = 'down'
    server.use(
      http.get(events(), () =>
        phase === 'down' ? HttpResponse.error() : sseResponse([planFrame, finalFrame]),
      ),
      http.get(status(), () =>
        HttpResponse.json({ run_id: RUN, conversation_id: 1, status: 'running', intent: null }),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('error'))
    expect(result.current.state.error?.code).toBe('CONNECTION_LOST')

    phase = 'up'
    act(() => result.current.reconnect())
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.error).toBeNull()
  })

  it('dự phòng cũng lỗi (404) → phase error với thông điệp của API', async () => {
    server.use(
      http.get(events(), () => HttpResponse.error()),
      http.get(status(), () =>
        HttpResponse.json(
          { error: { code: 'RUN_NOT_FOUND', message: 'Không tìm thấy lượt chạy', details: {} } },
          { status: 404 },
        ),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('error'))
    expect(result.current.state.error).toEqual({
      code: 'RUN_NOT_FOUND',
      message: 'Không tìm thấy lượt chạy',
    })
  })

  it('lỗi 4xx của luồng không thử lại, báo ngay thông điệp của API', async () => {
    let calls = 0
    server.use(
      http.get(events(), () => {
        calls += 1
        return HttpResponse.json(
          { error: { code: 'RUN_NOT_FOUND', message: 'Không tìm thấy lượt chạy', details: {} } },
          { status: 404 },
        )
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('error'))
    expect(calls).toBe(1)
    expect(result.current.state.error?.code).toBe('RUN_NOT_FOUND')
  })

  it('tháo component thì hủy yêu cầu đang treo và không cập nhật nữa', async () => {
    let aborted = false
    server.use(
      http.get(events(), ({ request }) => {
        request.signal.addEventListener('abort', () => {
          aborted = true
        })
        return sseResponse([planFrame], 'hang')
      }),
    )
    const { result, unmount } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('running'))
    unmount()
    await waitFor(() => expect(aborted).toBe(true))
  })
})
