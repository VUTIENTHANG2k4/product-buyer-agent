import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes, useLocation } from 'react-router'
import { apiUrl } from '@/api/client'
import { server } from '@/mocks/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { sample, sseFrame, sseResponse } from '@/test/sse'
import { ConversationPage } from './ConversationPage'

const RUN = 'run-1'
const RUN2 = 'run-2'

function Probe() {
  const location = useLocation()
  return <p data-testid="search">{location.search}</p>
}

function renderAt(route: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/c/:conversationId" element={<ConversationPage />} />
      </Routes>
      <Probe />
    </>,
    { route },
  )
}

const message = (id: number, role: 'user' | 'assistant', content: string) => ({
  message_id: id,
  role,
  content,
  payload: null,
  created_at: '2026-10-16T02:00:00Z',
})

function history(...items: ReturnType<typeof message>[]) {
  server.use(http.get(apiUrl('conversations/7/messages'), () => HttpResponse.json({ items })))
}

function run(id: string, frames: string[], then: 'close' | 'hang' = 'close') {
  server.use(http.get(apiUrl(`chat/${id}/events`), () => sseResponse(frames, then)))
}

const planFrame = sseFrame('plan', sample.plan, 0)
const finalFrame = sseFrame('final', sample.final, 1)
const composer = () => screen.getByRole('textbox', { name: 'Tin nhắn cho agent' })

describe('ConversationPage · mở lại hội thoại', () => {
  it('id không hợp lệ: báo không tìm thấy mà không gọi API, vẫn có đúng một h1', () => {
    let calls = 0
    server.use(
      http.get(apiUrl('conversations/:id/messages'), () => {
        calls += 1
        return HttpResponse.json({ items: [] })
      }),
    )
    renderAt('/c/abc')
    expect(screen.getByRole('alert')).toHaveTextContent('Không tìm thấy hội thoại này.')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(calls).toBe(0)
  })

  it.each(['0', '-3', '1.5', '99999999999', '2147483648', '1e3'])(
    'id %s ngoài miền khóa chính: coi là không tồn tại',
    (id) => {
      renderAt(`/c/${id}`)
      expect(screen.getByRole('alert')).toHaveTextContent('Hội thoại không tồn tại')
    },
  )

  it('đang tải: hiện skeleton; xong: hiện lịch sử theo thứ tự cũ → mới', async () => {
    history(message(1, 'user', 'laptop dưới 30 triệu'), message(2, 'assistant', 'Có **7** laptop.'))
    renderAt('/c/7')
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    expect(await screen.findByText('laptop dưới 30 triệu')).toBeInTheDocument()
    expect(screen.getByText('7').tagName).toBe('STRONG')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('lỗi 404 của hội thoại: hiện thông điệp của API và "Thử lại" tải lại được', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('conversations/7/messages'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { error: { code: 'NOT_FOUND', message: 'Không tìm thấy hội thoại 7', details: {} } },
              { status: 404 },
            )
          : HttpResponse.json({ items: [message(1, 'user', 'xin chào')] })
      }),
    )
    renderAt('/c/7')
    expect(await screen.findByRole('alert')).toHaveTextContent('Không tìm thấy hội thoại 7')
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('xin chào')).toBeInTheDocument()
  })

  it('lời nhắn của người dùng được hiện như văn bản, không dựng HTML', async () => {
    history(message(1, 'user', '<img src=x onerror=alert(1)> chuột'))
    const { container } = renderAt('/c/7')
    expect(await screen.findByText(/chuột/)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('ConversationPage · lượt đang theo dõi (?run=)', () => {
  it('phát lại lượt từ SSE: tin người dùng, kế hoạch và câu trả lời mỗi thứ đúng một lần', async () => {
    history(
      message(1, 'user', 'câu hỏi cũ'),
      message(2, 'assistant', 'trả lời cũ'),
      message(3, 'user', 'laptop gaming dưới 30 triệu'),
    )
    run(RUN, [
      planFrame,
      sseFrame('tool_start', sample.toolStart, 1),
      finalFrame.replace('id: 1', 'id: 2'),
    ])
    renderAt(`/c/7?run=${RUN}`)

    expect(await screen.findByText('Có 7 laptop phù hợp.')).toBeInTheDocument()
    expect(screen.getAllByText('laptop gaming dưới 30 triệu')).toHaveLength(1)
    expect(screen.getByText('câu hỏi cũ')).toBeInTheDocument()
    expect(screen.getByText('trả lời cũ')).toBeInTheDocument()
    expect(screen.getByText(sample.plan.steps[0] as string)).toBeInTheDocument()
  })

  it('lượt đã xong trước khi trang mở (lịch sử đã có câu trả lời): không hiện câu trả lời hai lần', async () => {
    history(
      message(1, 'user', 'laptop gaming dưới 30 triệu'),
      message(2, 'assistant', 'Câu trả lời đã lưu trong lịch sử'),
    )
    run(RUN, [planFrame, finalFrame])
    renderAt(`/c/7?run=${RUN}`)

    expect(await screen.findByText('Có 7 laptop phù hợp.')).toBeInTheDocument()
    expect(screen.queryByText('Câu trả lời đã lưu trong lịch sử')).toBeNull()
    expect(screen.getAllByText('laptop gaming dưới 30 triệu')).toHaveLength(1)
  })

  it('hiện mốc dữ liệu và gợi ý tiếp; bấm gợi ý gửi nó thành tin nhắn mới', async () => {
    history(message(1, 'user', 'laptop'))
    run(RUN, [planFrame, finalFrame])
    run(RUN2, [sseFrame('final', { ...sample.final, text: 'So sánh xong', suggestions: [] }, 0)])
    let body: unknown
    server.use(
      http.post(apiUrl('chat'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ run_id: RUN2, conversation_id: 7 }, { status: 202 })
      }),
    )
    renderAt(`/c/7?run=${RUN}`)

    await screen.findByText('Có 7 laptop phù hợp.')
    expect(screen.getByText(/^Dữ liệu cập nhật lúc 09:00 16\/10$/)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'So sánh 2 máy rẻ nhất' }))

    expect(await screen.findByText('So sánh xong')).toBeInTheDocument()
    expect(body).toEqual({ message: 'So sánh 2 máy rẻ nhất', conversation_id: 7 })
    expect(screen.getByText('So sánh 2 máy rẻ nhất', { selector: 'p' })).toBeInTheDocument()
  })

  it('agent hỏi lại: hiện câu hỏi nổi bật và để người dùng trả lời ở ô nhập', async () => {
    history(message(1, 'user', 'mua đồ'))
    run(RUN, [
      sseFrame('plan', { ...sample.plan, steps: [] }, 0),
      sseFrame('clarification', { question: 'Bạn muốn mua loại nào?' }, 1),
    ])
    renderAt(`/c/7?run=${RUN}`)

    expect(await screen.findByText('Bạn muốn mua loại nào?')).toBeInTheDocument()
    expect(screen.getByText('Agent cần hỏi thêm')).toBeInTheDocument()
    await waitFor(() => expect(composer()).toBeEnabled())
  })

  it('lỗi của agent (AGENT_STEP_LIMIT): hiện thông điệp; "Hỏi lại" gửi lại đúng tin nhắn đó', async () => {
    history(message(1, 'user', 'laptop rất phức tạp'))
    run(RUN, [
      planFrame,
      sseFrame(
        'error',
        { code: 'AGENT_STEP_LIMIT', message: 'Chưa xử lý xong trong số bước cho phép' },
        1,
      ),
    ])
    run(RUN2, [sseFrame('final', sample.final, 0)])
    let body: unknown
    server.use(
      http.post(apiUrl('chat'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ run_id: RUN2, conversation_id: 7 }, { status: 202 })
      }),
    )
    renderAt(`/c/7?run=${RUN}`)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Chưa xử lý xong trong số bước cho phép')
    await userEvent.click(within(alert).getByRole('button', { name: 'Hỏi lại' }))
    expect(await screen.findByText('Có 7 laptop phù hợp.')).toBeInTheDocument()
    expect(body).toEqual({ message: 'laptop rất phức tạp', conversation_id: 7 })
  })

  it('mất kết nối hẳn và lượt vẫn chạy: báo mất kết nối với nút Thử lại', async () => {
    history(message(1, 'user', 'laptop'))
    server.use(
      http.get(apiUrl(`chat/${RUN}/events`), () => HttpResponse.error()),
      http.get(apiUrl(`chat/${RUN}`), () =>
        HttpResponse.json({ run_id: RUN, conversation_id: 7, status: 'running', intent: null }),
      ),
    )
    renderAt(`/c/7?run=${RUN}`)
    const alert = await screen.findByRole('alert', undefined, { timeout: 8000 })
    expect(alert).toHaveTextContent('Mất kết nối tới máy chủ')
    expect(within(alert).getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
  }, 15000)
})

describe('ConversationPage · hỏi tiếp', () => {
  it('mất kết nối rồi bấm "Thử lại": ô nhập mở khi báo lỗi và khóa lại khi lượt nối lại đang chạy', async () => {
    history(message(1, 'user', 'laptop'))
    server.use(
      http.get(apiUrl(`chat/${RUN}/events`), () => HttpResponse.error()),
      http.get(apiUrl(`chat/${RUN}`), () =>
        HttpResponse.json({ run_id: RUN, conversation_id: 7, status: 'running', intent: null }),
      ),
    )
    renderAt(`/c/7?run=${RUN}`)
    const alert = await screen.findByRole('alert', undefined, { timeout: 8000 })
    expect(composer()).toBeEnabled()

    run(RUN, [planFrame], 'hang')
    await userEvent.click(within(alert).getByRole('button', { name: 'Thử lại' }))
    await screen.findByText(sample.plan.steps[0] as string)
    expect(composer()).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Gửi' })).toBeDisabled()
  }, 15000)

  it('trong lúc lượt chạy dở, ô nhập và nút Gửi bị tắt', async () => {
    history(message(1, 'user', 'laptop'))
    run(RUN, [planFrame], 'hang')
    renderAt(`/c/7?run=${RUN}`)
    await screen.findByText(sample.plan.steps[0] as string)
    expect(composer()).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Gửi' })).toBeDisabled()
  })

  it('gửi câu hỏi tiếp: gắn conversation_id, thêm lượt mới và đổi ?run= sang lượt mới', async () => {
    history(message(1, 'user', 'laptop'))
    run(RUN, [planFrame, finalFrame])
    run(RUN2, [
      sseFrame('final', { ...sample.final, text: 'Câu trả lời thứ hai', suggestions: [] }, 0),
    ])
    let body: unknown
    server.use(
      http.post(apiUrl('chat'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ run_id: RUN2, conversation_id: 7 }, { status: 202 })
      }),
    )
    renderAt(`/c/7?run=${RUN}`)
    await screen.findByText('Có 7 laptop phù hợp.')
    await waitFor(() => expect(composer()).toBeEnabled())

    await userEvent.type(composer(), 'chuột không dây{Enter}')

    expect(await screen.findByText('Câu trả lời thứ hai')).toBeInTheDocument()
    expect(body).toEqual({ message: 'chuột không dây', conversation_id: 7 })
    expect(screen.getByText('chuột không dây')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('search')).toHaveTextContent(`?run=${RUN2}`))
    expect(screen.getByText('Có 7 laptop phù hợp.')).toBeInTheDocument()
  })

  it('gửi lỗi (409/503...): hiện thông điệp dưới ô nhập, giữ nội dung đã gõ', async () => {
    history(message(1, 'user', 'a'), message(2, 'assistant', 'b'))
    server.use(
      http.post(apiUrl('chat'), () =>
        HttpResponse.json(
          { error: { code: 'LLM_UNAVAILABLE', message: 'Không gọi được LLM', details: {} } },
          { status: 503 },
        ),
      ),
    )
    renderAt('/c/7')
    await screen.findByText('b')
    await userEvent.type(composer(), 'hỏi tiếp{Enter}')
    expect(await screen.findByText('Không gọi được LLM')).toBeInTheDocument()
    expect(composer()).toHaveValue('hỏi tiếp')
  })

  it('chuyển sang hội thoại khác thì dựng lại, không lẫn lịch sử', async () => {
    server.use(
      http.get(apiUrl('conversations/7/messages'), () =>
        HttpResponse.json({ items: [message(1, 'user', 'của hội thoại 7')] }),
      ),
      http.get(apiUrl('conversations/8/messages'), () =>
        HttpResponse.json({ items: [message(2, 'user', 'của hội thoại 8')] }),
      ),
    )
    const first = renderAt('/c/7')
    expect(await screen.findByText('của hội thoại 7')).toBeInTheDocument()
    first.unmount()
    renderAt('/c/8')
    expect(await screen.findByText('của hội thoại 8')).toBeInTheDocument()
    expect(screen.queryByText('của hội thoại 7')).toBeNull()
  })
})
