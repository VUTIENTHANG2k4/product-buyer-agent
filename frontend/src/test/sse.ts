import { HttpResponse } from 'msw'

/** Một khung SSE đúng định dạng máy chủ: `event:`, `data:` (JSON) và `id:`. */
export function sseFrame(event: string, data: unknown, id?: number): string {
  const idLine = id === undefined ? '' : `id: ${id}\n`
  return `event: ${event}\n${idLine}data: ${JSON.stringify(data)}\n\n`
}

/**
 * Phản hồi `text/event-stream` cho MSW. Mỗi phần tử của `chunks` là một lần đọc của luồng, nên test
 * có thể cắt khung SSE ở vị trí bất kỳ. `then` cho phép giữ luồng mở (không đóng) hoặc làm nó lỗi.
 */
export function sseResponse(
  chunks: string[],
  then: 'close' | 'hang' | 'error' = 'close',
): Response {
  const encoder = new TextEncoder()
  let sent = 0
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (sent < chunks.length) {
        controller.enqueue(encoder.encode(chunks[sent]))
        sent += 1
        return
      }
      if (then === 'close') controller.close()
      else if (then === 'error') {
        // Chờ một nhịp để phần đã gửi kịp được đọc trước khi luồng lỗi (lỗi làm bỏ phần chưa đọc).
        await new Promise((resolve) => setTimeout(resolve, 20))
        controller.error(new TypeError('network error'))
      } else await new Promise<void>(() => undefined)
    },
  })
  return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
}

/** Dữ liệu mẫu cho các sự kiện agent (hư cấu). */
export const sample = {
  plan: {
    intent: { category: 'laptop', tier: 1, plan_steps: ['Tìm laptop', 'Lọc theo giá'] },
    steps: ['Tìm laptop trong danh mục đã thu thập', 'Lọc giá ≤ 30.000.000 ₫'],
  },
  toolStart: { call_id: 'c1', tool: 'search_catalog', args_summary: 'laptop, ≤ 30.000.000 ₫' },
  toolEnd: {
    call_id: 'c1',
    tool: 'search_catalog',
    ok: true,
    summary: 'Tìm thấy 7 sản phẩm',
    duration_ms: 84,
  },
  final: {
    text: 'Có 7 laptop phù hợp.',
    table: [],
    live_items: [],
    suggestions: ['So sánh 2 máy rẻ nhất', 'Đặt cảnh báo giá'],
    data_as_of: '2026-10-16T02:00:00Z',
  },
}
