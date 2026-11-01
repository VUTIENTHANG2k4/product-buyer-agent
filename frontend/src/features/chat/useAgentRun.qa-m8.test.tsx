import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { server } from '@/mocks/server'
import { sample, sseFrame, sseResponse } from '@/test/sse'
import { useAgentRun } from './useAgentRun'

const RUN = '3f1c2d4e-0000-4000-8000-0000000000aa'
const events = () => apiUrl(`chat/${RUN}/events`)
const status = () => apiUrl(`chat/${RUN}`)
const FAST = { reconnectDelaysMs: [0, 0, 0] }

function render(runId: string | null = RUN) {
  return renderHook(() => useAgentRun(runId, FAST))
}

/** Luồng thô: mỗi phần tử của `chunks` là một lần đọc (có thể cắt giữa ký tự nhiều byte). */
function rawStream(chunks: Uint8Array[], then: 'close' | 'hang' = 'close'): Response {
  return new HttpResponse(
    new ReadableStream<Uint8Array>({
      async start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk)
        if (then === 'close') controller.close()
        else await new Promise<void>(() => undefined)
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}

const encoder = new TextEncoder()
const bytewise = (text: string) => Array.from(encoder.encode(text), (byte) => Uint8Array.of(byte))

const finalOf = (text: string) => ({ ...sample.final, text })

describe('useAgentRun · luồng SSE biên (QA M8)', () => {
  it('nhận từng byte một: tiếng Việt có dấu tổ hợp và emoji (4 byte) không bị vỡ', async () => {
    // NFD: "e" + dấu mũ + dấu nặng; emoji ngoài BMP nằm trong cả văn bản lẫn tên bước.
    const composed = 'Kệ hoạch 🛒 laptop – Đà Nẵng 🇻🇳'
    const text = composed.normalize('NFD')
    expect(text.length).toBeGreaterThan(composed.length)
    const body =
      sseFrame('plan', sample.plan, 0).replace(/\n/g, '\r\n') + sseFrame('final', finalOf(text), 1)
    server.use(http.get(events(), () => rawStream(bytewise(body))))
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.final?.text).toBe(text)
    expect(result.current.state.steps).toEqual(sample.plan.steps)
  })

  it('luồng CRLF như máy chủ thật (có ping và id bắt đầu từ 0) được xử lý đủ', async () => {
    const crlf = (frame: string) => frame.replace(/\n/g, '\r\n')
    const body =
      ': ping\r\n\r\n' +
      crlf(sseFrame('plan', sample.plan, 0)) +
      ': ping\r\n\r\n' +
      crlf(sseFrame('tool_start', sample.toolStart, 1)) +
      crlf(sseFrame('tool_end', sample.toolEnd, 2)) +
      crlf(sseFrame('final', sample.final, 3))
    server.use(http.get(events(), () => rawStream([encoder.encode(body)])))
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.lastEventId).toBe(3)
    expect(result.current.state.tools).toHaveLength(1)
  })

  it('câu trả lời 1 MB trong một dòng data, đến từng mảnh 16 KB, được giữ nguyên', async () => {
    const text = 'Đà Nẵng '.repeat(131_072) // ~1 MB ký tự
    const bytes = encoder.encode(sseFrame('final', finalOf(text), 0))
    const chunks: Uint8Array[] = []
    for (let i = 0; i < bytes.length; i += 16_384) chunks.push(bytes.slice(i, i + 16_384))
    server.use(http.get(events(), () => rawStream(chunks)))
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.final?.text.length).toBe(text.length)
    expect(result.current.state.final?.text).toBe(text)
  })

  it('sự kiện đến sau final (cùng lần đọc) bị bỏ, không nối lại và không đổi câu trả lời', async () => {
    let calls = 0
    server.use(
      http.get(events(), () => {
        calls += 1
        return sseResponse([
          sseFrame('final', finalOf('Câu trả lời thật'), 0) +
            sseFrame('final', finalOf('Câu trả lời giả'), 1) +
            sseFrame('error', { code: 'INTERNAL_ERROR', message: 'muộn' }, 2),
        ])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.final?.text).toBe('Câu trả lời thật')
    expect(result.current.state.error).toBeNull()
    expect(result.current.state.lastEventId).toBe(0)
    expect(calls).toBe(1)
  })

  it('id nhảy cóc (0 → 10) vẫn được nhận và Last-Event-ID khi nối lại là id lớn nhất', async () => {
    const headers: (string | null)[] = []
    server.use(
      http.get(events(), ({ request }) => {
        headers.push(request.headers.get('Last-Event-ID'))
        return headers.length === 1
          ? sseResponse([
              sseFrame('plan', sample.plan, 0) + sseFrame('tool_start', sample.toolStart, 10),
            ])
          : sseResponse([sseFrame('final', sample.final, 11)])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(headers).toEqual([null, '10'])
  })

  it('id 0 là id hợp lệ: nối lại gửi Last-Event-ID "0", không coi là chưa có', async () => {
    const headers: (string | null)[] = []
    server.use(
      http.get(events(), ({ request }) => {
        headers.push(request.headers.get('Last-Event-ID'))
        return headers.length === 1
          ? sseResponse([sseFrame('plan', sample.plan, 0)])
          : sseResponse([sseFrame('final', sample.final, 1)])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(headers).toEqual([null, '0'])
  })

  it('id âm hoặc không phải số được coi như không có id: sự kiện vẫn xử lý, lastEventId không đổi', async () => {
    server.use(
      http.get(events(), () =>
        sseResponse([
          sseFrame('plan', sample.plan, 4) +
            'event: tool_start\nid: -1\ndata: ' +
            JSON.stringify(sample.toolStart) +
            '\n\n' +
            'event: tool_end\nid: abc\ndata: ' +
            JSON.stringify(sample.toolEnd) +
            '\n\n' +
            sseFrame('final', sample.final, 5),
        ]),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.tools[0]?.status).toBe('ok')
    expect(result.current.state.lastEventId).toBe(5)
  })

  it('JSON hỏng ở giữa luồng bị bỏ qua, các sự kiện sau vẫn tới', async () => {
    server.use(
      http.get(events(), () =>
        sseResponse([
          sseFrame('plan', sample.plan, 0) +
            'event: tool_start\nid: 1\ndata: {"call_id": "c1", "tool"\n\n' +
            'event: tool_end\nid: 2\ndata: [1,2,3]\n\n' +
            'event: plan\nid: 3\ndata: null\n\n' +
            sseFrame('final', sample.final, 4),
        ]),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(result.current.state.tools).toEqual([])
    expect(result.current.state.steps).toEqual(sample.plan.steps)
  })

  it('final thiếu text/table (sai schema) bị bỏ; luồng đóng thì dự phòng GET xử lý tiếp', async () => {
    server.use(
      http.get(events(), () => sseResponse([sseFrame('final', { text: 'chỉ có chữ' }, 0)])),
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
    expect(result.current.state.final?.text).toBe(sample.final.text)
  })

  it('502 với thân HTML (proxy hỏng) được thử lại như lỗi mạng, sau đó luồng chạy bình thường', async () => {
    let calls = 0
    server.use(
      http.get(events(), () => {
        calls += 1
        return calls < 3
          ? new HttpResponse('<html>Bad Gateway</html>', {
              status: 502,
              headers: { 'Content-Type': 'text/html' },
            })
          : sseResponse([sseFrame('final', sample.final, 0)])
      }),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
    expect(calls).toBe(3)
  })

  it('tháo component trong lúc chờ nối lại: không có yêu cầu nối lại nào nữa', async () => {
    let calls = 0
    server.use(
      http.get(events(), () => {
        calls += 1
        return sseResponse([sseFrame('plan', sample.plan, 0)])
      }),
    )
    const { result, unmount } = renderHook(() =>
      useAgentRun(RUN, { reconnectDelaysMs: [150, 150, 150] }),
    )
    await waitFor(() => expect(result.current.state.phase).toBe('running'))
    expect(calls).toBe(1)
    unmount()
    await new Promise((resolve) => setTimeout(resolve, 400))
    expect(calls).toBe(1)
  })

  it('runId null rồi có giá trị: bắt đầu kết nối khi runId xuất hiện', async () => {
    server.use(http.get(events(), () => sseResponse([sseFrame('final', sample.final, 0)])))
    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) => useAgentRun(id, FAST),
      {
        initialProps: { id: null as string | null },
      },
    )
    expect(result.current.state.phase).toBe('connecting')
    rerender({ id: RUN })
    await waitFor(() => expect(result.current.state.phase).toBe('done'))
  })

  // BUG-M8-2: `SseParser` giữ `id` của sự kiện trước cho sự kiện không có dòng `id:` (đúng đặc tả),
  // `followRun` lại coi đó là id của sự kiện mới. Reducer bỏ sự kiện "trùng id", nhưng `followRun` vẫn
  // coi `error`/`final` là kết thúc và dừng: giao diện kẹt ở "running" mãi. Máy chủ hiện luôn gửi `id`
  // nên chưa xảy ra; sửa: chỉ dùng id khi chính sự kiện đó có dòng `id:`. XPASS báo đỏ: gỡ `.fails`.
  it('sự kiện error không có dòng id (sau sự kiện có id) vẫn được hiện ra', async () => {
    server.use(
      http.get(events(), () =>
        sseResponse([
          sseFrame('plan', sample.plan, 0) +
            sseFrame('error', { code: 'INTERNAL_ERROR', message: 'Máy chủ gặp lỗi' }),
        ]),
      ),
      http.get(status(), () =>
        HttpResponse.json({ run_id: RUN, conversation_id: 1, status: 'running', intent: null }),
      ),
    )
    const { result } = render()
    await waitFor(() => expect(result.current.state.phase).toBe('error'), { timeout: 1500 })
    expect(result.current.state.error?.message).toBe('Máy chủ gặp lỗi')
  })
})
