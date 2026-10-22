import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes, useLocation } from 'react-router'
import { apiUrl } from '@/api/client'
import { server } from '@/mocks/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { HomePage } from './HomePage'

function Where() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname + location.search}</p>
}

function renderHome() {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/c/:id" element={<Where />} />
    </Routes>,
  )
}

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString()

function catalog(dataAsOf: string | null, total = 10) {
  server.use(
    http.get(apiUrl('products'), () =>
      HttpResponse.json({
        items: [],
        total,
        page: 1,
        page_size: 1,
        stale: false,
        data_as_of: dataAsOf,
      }),
    ),
  )
}

const composer = () => screen.getByRole('textbox', { name: 'Tin nhắn cho agent' })

describe('HomePage · nội dung', () => {
  it('hiện tiêu đề, ô nhập và bốn gợi ý mẫu', () => {
    renderHome()
    expect(
      screen.getByRole('heading', { level: 1, name: 'Bạn muốn mua gì hôm nay?' }),
    ).toBeInTheDocument()
    expect(composer()).toBeInTheDocument()
    const group = screen.getByRole('group', { name: 'Gợi ý' })
    expect(group.querySelectorAll('button')).toHaveLength(4)
    expect(screen.getByRole('button', { name: 'Laptop gaming dưới 25 triệu' })).toBeInTheDocument()
  })

  it('đang tải thông tin danh mục: hiện skeleton, sau đó nguồn và mốc cập nhật', async () => {
    catalog(hoursAgo(2))
    renderHome()
    expect(screen.queryByText(/Nguồn:/)).toBeNull()
    expect(await screen.findByText('Nguồn: GearVN · FPT Shop · An Phát')).toBeInTheDocument()
    expect(screen.getByText('Cập nhật: 2 giờ trước')).toBeInTheDocument()
    expect(screen.queryByText(/Giá cập nhật lúc/)).toBeNull()
  })

  it('dữ liệu cũ hơn 24 giờ: thêm badge vàng', async () => {
    catalog(hoursAgo(72))
    renderHome()
    expect(await screen.findByText('Cập nhật: 3 ngày trước')).toBeInTheDocument()
    expect(screen.getByText(/^Giá cập nhật lúc \d{2}:\d{2} \d{2}\/\d{2}$/)).toBeInTheDocument()
  })

  it('danh mục rỗng: giải thích và trỏ tới trang Quản trị', async () => {
    catalog(null, 0)
    renderHome()
    expect(await screen.findByText(/Chưa có dữ liệu sản phẩm/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Quản trị' })).toHaveAttribute('href', '/admin')
    expect(screen.queryByText(/Nguồn:/)).toBeNull()
  })

  it('lỗi tải thông tin danh mục: không hiện hộp lỗi, ô nhập vẫn dùng được', async () => {
    server.use(http.get(apiUrl('products'), () => HttpResponse.error()))
    renderHome()
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
    expect(screen.queryByRole('alert')).toBeNull()
    expect(composer()).toBeEnabled()
  })
})

describe('HomePage · hội thoại gần đây', () => {
  it('liệt kê liên kết tới từng hội thoại, tiêu đề trống dùng tên mặc định', async () => {
    server.use(
      http.get(apiUrl('conversations'), () =>
        HttpResponse.json({
          items: [
            {
              conversation_id: 9,
              title: 'laptop gaming dưới 30 triệu',
              created_at: '2026-10-16T02:00:00Z',
            },
            { conversation_id: 8, title: null, created_at: '2026-10-15T02:00:00Z' },
          ],
        }),
      ),
    )
    renderHome()
    const link = await screen.findByRole('link', { name: 'laptop gaming dưới 30 triệu' })
    expect(link).toHaveAttribute('href', '/c/9')
    expect(screen.getByRole('link', { name: 'Hội thoại chưa đặt tên' })).toHaveAttribute(
      'href',
      '/c/8',
    )
    expect(screen.getByRole('heading', { name: 'Hội thoại gần đây' })).toBeInTheDocument()
  })

  it('chưa có hội thoại: không hiện mục này', async () => {
    renderHome()
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Hội thoại gần đây' })).toBeNull(),
    )
  })
})

describe('HomePage · gửi câu hỏi', () => {
  it('gửi tin, rồi chuyển sang /c/:id kèm run_id', async () => {
    let body: unknown
    server.use(
      http.post(apiUrl('chat'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ run_id: 'run-abc', conversation_id: 5 }, { status: 202 })
      }),
    )
    renderHome()
    await userEvent.type(composer(), 'laptop gaming dưới 30 triệu{Enter}')

    expect(await screen.findByTestId('where')).toHaveTextContent('/c/5?run=run-abc')
    expect(body).toEqual({ message: 'laptop gaming dưới 30 triệu' })
  })

  it('bấm một gợi ý gửi đúng nội dung gợi ý', async () => {
    let body: unknown
    server.use(
      http.post(apiUrl('chat'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ run_id: 'r1', conversation_id: 1 }, { status: 202 })
      }),
    )
    renderHome()
    await userEvent.click(screen.getByRole('button', { name: 'Tai nghe có mic dưới 2 triệu' }))
    await screen.findByTestId('where')
    expect(body).toEqual({ message: 'Tai nghe có mic dưới 2 triệu' })
  })

  it('lỗi từ máy chủ (503 LLM_UNAVAILABLE): hiện thông điệp, giữ nội dung đã nhập và ở lại trang', async () => {
    server.use(
      http.post(apiUrl('chat'), () =>
        HttpResponse.json(
          { error: { code: 'LLM_UNAVAILABLE', message: 'Không gọi được LLM', details: {} } },
          { status: 503 },
        ),
      ),
    )
    renderHome()
    await userEvent.type(composer(), 'chuột không dây{Enter}')

    expect(await screen.findByRole('alert')).toHaveTextContent('Không gọi được LLM')
    expect(composer()).toHaveValue('chuột không dây')
    expect(screen.queryByTestId('where')).toBeNull()
  })

  it('lỗi gửi từ gợi ý cũng hiện thông điệp và không văng lỗi chưa xử lý', async () => {
    server.use(http.post(apiUrl('chat'), () => HttpResponse.error()))
    renderHome()
    await userEvent.click(screen.getByRole('button', { name: 'Laptop gaming dưới 25 triệu' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Không kết nối được máy chủ')
  })

  it('đang gửi: nút Gửi và các gợi ý bị tắt để không gửi hai lần', async () => {
    let release: () => void = () => undefined
    server.use(
      http.post(apiUrl('chat'), async () => {
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return HttpResponse.json({ run_id: 'r1', conversation_id: 1 }, { status: 202 })
      }),
    )
    renderHome()
    await userEvent.type(composer(), 'laptop{Enter}')
    expect(await screen.findByRole('button', { name: 'Đang gửi…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Laptop gaming dưới 25 triệu' })).toBeDisabled()
    release()
    await screen.findByTestId('where')
  })
})
