import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router'
import { apiUrl } from '@/api/client'
import { alertView } from '@/mocks/data'
import { server } from '@/mocks/server'
import { installFakeAlerts } from '@/test/fakeAlerts'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AlertsPage } from './AlertsPage'

let media: MatchMediaControl

beforeEach(() => {
  media = mockMatchMedia(true)
})
afterEach(() => media.restore())

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/alerts" element={<AlertsPage />} />
    </Routes>,
    { route: '/alerts' },
  )
}

const laptop = alertView({
  alert_id: 1,
  product_id: 12,
  product_name: 'MockBook Gaming 15',
  target_price: 26_000_000,
  current_best_price: 27_490_000,
})
const reached = alertView({
  alert_id: 2,
  product_id: 20,
  product_name: 'Chuột Mock M1',
  target_price: 600_000,
  current_best_price: 550_000,
  channel: 'telegram',
  destination: '@mock_chat',
  status: 'triggered',
  last_notified_price: 580_000,
  last_notified_at: '2026-10-15T03:30:00Z',
})
const paused = alertView({
  alert_id: 3,
  product_id: 30,
  product_name: 'Tai nghe Mock H1',
  target_price: 1_000_000,
  current_best_price: null,
  status: 'paused',
})

function row(name: string): HTMLElement {
  return screen.getByRole('link', { name }).closest('tr') as HTMLElement
}

describe('AlertsPage · trạng thái màn hình', () => {
  it('đang tải: có vùng báo bận và tiêu đề trang vẫn hiện', () => {
    server.use(http.get(apiUrl('alerts'), () => new Promise(() => undefined)))
    renderPage()
    expect(screen.getByRole('heading', { level: 1, name: 'Cảnh báo giá' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
  })

  it('chưa có cảnh báo: giải thích cách tạo và có nút nhờ agent', async () => {
    installFakeAlerts([])
    renderPage()
    expect(await screen.findByText('Bạn chưa đặt cảnh báo giá nào')).toBeInTheDocument()
    expect(screen.getByText(/chọn "Báo khi giảm giá"/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Nhờ agent tìm sản phẩm' })).toHaveAttribute(
      'href',
      '/',
    )
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('lỗi máy chủ: hiện thông điệp tiếng Việt và "Thử lại" tải lại được', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('alerts'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { error: { code: 'INTERNAL_ERROR', message: 'Lỗi hệ thống', details: {} } },
              { status: 500 },
            )
          : HttpResponse.json({ items: [laptop] })
      }),
    )
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('Không tải được cảnh báo')).toBeInTheDocument()
    expect(within(alert).getByText('Lỗi hệ thống')).toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByRole('link', { name: 'MockBook Gaming 15' })).toBeInTheDocument()
  })
})

describe('AlertsPage · bảng cảnh báo', () => {
  it('mỗi hàng: sản phẩm (liên kết), giá hiện tại, ngưỡng, kênh + nơi nhận, trạng thái', async () => {
    installFakeAlerts([laptop, reached, paused])
    renderPage()
    await screen.findByRole('table', { name: 'Danh sách cảnh báo giá' })

    const first = within(row('MockBook Gaming 15'))
    expect(screen.getByRole('link', { name: 'MockBook Gaming 15' })).toHaveAttribute(
      'href',
      '/products/12',
    )
    expect(first.getByText('27.490.000 ₫')).toBeInTheDocument()
    expect(first.getByText('26.000.000 ₫')).toBeInTheDocument()
    expect(first.getByText('Email')).toBeInTheDocument()
    expect(first.getByText('mock@example.com')).toBeInTheDocument()
    expect(first.getByText('Đang theo dõi')).toBeInTheDocument()
    expect(first.getByText('Chưa báo lần nào')).toBeInTheDocument()
    expect(first.queryByText('Đã tới ngưỡng')).toBeNull()

    const second = within(row('Chuột Mock M1'))
    expect(second.getByText('Telegram')).toBeInTheDocument()
    expect(second.getByText('@mock_chat')).toBeInTheDocument()
    expect(second.getByText('Đã báo')).toBeInTheDocument()
    expect(second.getByText('10:30 15/10/2026')).toBeInTheDocument()
    expect(second.getByText('580.000 ₫')).toBeInTheDocument()
    expect(second.getByText('Đã tới ngưỡng')).toBeInTheDocument()

    const third = within(row('Tai nghe Mock H1'))
    expect(third.getByText('Tạm dừng', { selector: '[data-slot="badge"]' })).toBeInTheDocument()
    expect(third.getByText('Chưa có giá')).toBeInTheDocument()
  })

  it('giá đúng bằng ngưỡng cũng tính là đã tới ngưỡng; cao hơn 1 ₫ thì chưa', async () => {
    installFakeAlerts([
      alertView({
        alert_id: 1,
        product_name: 'Bằng ngưỡng',
        target_price: 100,
        current_best_price: 100,
      }),
      alertView({
        alert_id: 2,
        product_name: 'Hơn 1 đồng',
        target_price: 100,
        current_best_price: 101,
      }),
    ])
    renderPage()
    await screen.findByRole('table')
    expect(within(row('Bằng ngưỡng')).getByText('Đã tới ngưỡng')).toBeInTheDocument()
    expect(within(row('Hơn 1 đồng')).queryByText('Đã tới ngưỡng')).toBeNull()
  })

  it('lần báo gần nhất có thời gian nhưng thiếu giá: chỉ hiện thời gian', async () => {
    installFakeAlerts([
      alertView({ last_notified_at: '2026-10-15T03:30:00Z', last_notified_price: null }),
    ])
    renderPage()
    await screen.findByRole('table')
    expect(screen.getByText('10:30 15/10/2026')).toBeInTheDocument()
    expect(screen.queryByText('Chưa báo lần nào')).toBeNull()
  })

  it('màn hình hẹp (< 640 px): dạng thẻ có đủ nội dung và thao tác như bảng', async () => {
    media.set(false)
    installFakeAlerts([laptop, reached])
    renderPage()
    const list = await screen.findByRole('list', { name: 'Danh sách cảnh báo giá' })
    expect(screen.queryByRole('table')).toBeNull()
    const cards = within(list).getAllByRole('listitem')
    expect(cards).toHaveLength(2)

    const card = within(cards[1] as HTMLElement)
    expect(card.getByRole('link', { name: 'Chuột Mock M1' })).toHaveAttribute(
      'href',
      '/products/20',
    )
    expect(card.getByText('Đã báo')).toBeInTheDocument()
    expect(card.getByText('550.000 ₫')).toBeInTheDocument()
    expect(card.getByText('Telegram')).toBeInTheDocument()
    expect(card.getByRole('button', { name: 'Gửi thử: Chuột Mock M1' })).toBeInTheDocument()
  })
})

describe('AlertsPage · lọc theo trạng thái', () => {
  it('chọn trạng thái gọi API với ?status= và chỉ hiện cảnh báo khớp', async () => {
    const fake = installFakeAlerts([laptop, reached, paused])
    renderPage()
    await screen.findByRole('table')
    expect(fake.reads).toEqual(['alerts'])

    await userEvent.selectOptions(screen.getByLabelText('Lọc theo trạng thái'), 'Tạm dừng')
    await waitFor(() =>
      expect(screen.queryByRole('link', { name: 'MockBook Gaming 15' })).toBeNull(),
    )
    expect(fake.reads).toContain('alerts?status=paused')
    expect(screen.getByRole('link', { name: 'Tai nghe Mock H1' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Chuột Mock M1' })).toBeNull()
  })

  it('bộ lọc không có kết quả: báo riêng, không nhầm với "chưa đặt cảnh báo nào"', async () => {
    installFakeAlerts([laptop])
    renderPage()
    await screen.findByRole('table')
    await userEvent.selectOptions(screen.getByLabelText('Lọc theo trạng thái'), 'Đã báo')
    expect(await screen.findByText('Không có cảnh báo nào ở trạng thái này')).toBeInTheDocument()
    expect(screen.queryByText('Bạn chưa đặt cảnh báo giá nào')).toBeNull()

    await userEvent.selectOptions(screen.getByLabelText('Lọc theo trạng thái'), 'Tất cả trạng thái')
    expect(await screen.findByRole('link', { name: 'MockBook Gaming 15' })).toBeInTheDocument()
  })
})

describe('AlertsPage · tạm dừng và tiếp tục', () => {
  it('đang theo dõi → "Tạm dừng" gửi PATCH status=paused, rồi hàng hiện "Tạm dừng" và nút "Tiếp tục"', async () => {
    const fake = installFakeAlerts([laptop])
    renderPage()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: 'Tạm dừng: MockBook Gaming 15' }))
    await waitFor(() =>
      expect(
        within(row('MockBook Gaming 15')).getByText('Tạm dừng', {
          selector: '[data-slot="badge"]',
        }),
      ).toBeInTheDocument(),
    )
    expect(fake.writes).toEqual(['PATCH alerts/1 {"status":"paused"}'])

    await userEvent.click(screen.getByRole('button', { name: 'Tiếp tục: MockBook Gaming 15' }))
    await waitFor(() =>
      expect(within(row('MockBook Gaming 15')).getByText('Đang theo dõi')).toBeInTheDocument(),
    )
    expect(fake.writes[1]).toBe('PATCH alerts/1 {"status":"active"}')
  })

  it('cảnh báo đã báo → "Theo dõi lại" đặt về active', async () => {
    const fake = installFakeAlerts([reached])
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Theo dõi lại: Chuột Mock M1' }))
    await waitFor(() =>
      expect(within(row('Chuột Mock M1')).getByText('Đang theo dõi')).toBeInTheDocument(),
    )
    expect(fake.writes).toEqual(['PATCH alerts/2 {"status":"active"}'])
  })

  it('đang gửi: nút bị tắt để không bấm đôi', async () => {
    const fake = installFakeAlerts([laptop])
    let release: () => void = () => undefined
    fake.hold = new Promise((resolve) => {
      release = resolve
    })
    renderPage()
    await screen.findByRole('table')
    const button = screen.getByRole('button', { name: 'Tạm dừng: MockBook Gaming 15' })
    await userEvent.click(button)
    await waitFor(() => expect(button).toBeDisabled())
    expect(fake.writes).toHaveLength(1)
    release()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Tiếp tục: MockBook Gaming 15' })).toBeEnabled(),
    )
  })

  it('máy chủ từ chối: giữ nguyên trạng thái cũ và hiện thông điệp lỗi ngay tại hàng', async () => {
    const fake = installFakeAlerts([laptop])
    fake.failWrites = {
      status: 409,
      code: 'DUPLICATE_ALERT',
      message: 'Đã có cảnh báo cùng ngưỡng đang hiệu lực',
    }
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Tạm dừng: MockBook Gaming 15' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Không thực hiện được')
    expect(alert).toHaveTextContent('Đã có cảnh báo cùng ngưỡng đang hiệu lực')
    expect(within(row('MockBook Gaming 15')).getByText('Đang theo dõi')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tạm dừng: MockBook Gaming 15' })).toBeEnabled()
  })
})

describe('AlertsPage · gửi thử', () => {
  it('hiện đúng lý do máy chủ trả, không báo "đã gửi" khi sent=false', async () => {
    const fake = installFakeAlerts([laptop])
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi thử: MockBook Gaming 15' }))
    expect(
      await screen.findByText('Chưa gửi được thông báo thử: Bộ gửi thông báo chưa được cấu hình.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Đã gửi thông báo thử.')).toBeNull()
    expect(fake.writes).toEqual(['POST alerts/1/test'])
  })

  it('sent=false không có lý do: thông điệp chung, vẫn không nói đã gửi', async () => {
    const fake = installFakeAlerts([laptop])
    fake.testResult = { sent: false, reason: null }
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi thử: MockBook Gaming 15' }))
    expect(await screen.findByText('Chưa gửi được thông báo thử.')).toBeInTheDocument()
  })

  it('sent=true (khi M9 có bộ gửi): báo đã gửi', async () => {
    const fake = installFakeAlerts([laptop])
    fake.testResult = { sent: true, reason: null }
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi thử: MockBook Gaming 15' }))
    expect(await screen.findByText('Đã gửi thông báo thử.')).toBeInTheDocument()
  })

  it('kết quả gắn đúng hàng được gửi thử, hàng khác không bị ảnh hưởng', async () => {
    installFakeAlerts([laptop, reached])
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi thử: Chuột Mock M1' }))
    expect(await within(row('Chuột Mock M1')).findByRole('status')).toHaveTextContent(
      'Chưa gửi được thông báo thử',
    )
    expect(within(row('MockBook Gaming 15')).queryByRole('status')).toBeNull()
  })

  it('cảnh báo đã bị xóa ở nơi khác (404): hiện lỗi của máy chủ', async () => {
    const fake = installFakeAlerts([laptop])
    renderPage()
    await screen.findByRole('table')
    fake.alerts = []
    await userEvent.click(screen.getByRole('button', { name: 'Gửi thử: MockBook Gaming 15' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Không tìm thấy cảnh báo')
  })
})

describe('AlertsPage · xóa cảnh báo', () => {
  it('hỏi xác nhận; Hủy thì không gọi API và vẫn còn hàng', async () => {
    const fake = installFakeAlerts([laptop])
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Xóa: MockBook Gaming 15' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(
      within(dialog).getByText('Xóa cảnh báo giá cho "MockBook Gaming 15"?'),
    ).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Hủy' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(fake.writes).toEqual([])
    expect(screen.getByRole('link', { name: 'MockBook Gaming 15' })).toBeInTheDocument()
  })

  it('xác nhận: gửi DELETE, hàng biến mất, các hàng khác còn nguyên', async () => {
    const fake = installFakeAlerts([laptop, reached])
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Xóa: MockBook Gaming 15' }))
    await userEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Xóa cảnh báo',
      }),
    )
    await waitFor(() =>
      expect(screen.queryByRole('link', { name: 'MockBook Gaming 15' })).toBeNull(),
    )
    expect(fake.writes).toEqual(['DELETE alerts/1'])
    expect(screen.getByRole('link', { name: 'Chuột Mock M1' })).toBeInTheDocument()
  })

  it('xóa cảnh báo cuối cùng: chuyển sang trạng thái rỗng', async () => {
    installFakeAlerts([laptop])
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Xóa: MockBook Gaming 15' }))
    await userEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Xóa cảnh báo',
      }),
    )
    expect(await screen.findByText('Bạn chưa đặt cảnh báo giá nào')).toBeInTheDocument()
  })

  it('máy chủ từ chối: đóng hộp thoại, giữ hàng và báo lỗi', async () => {
    const fake = installFakeAlerts([laptop])
    fake.failWrites = { status: 500, code: 'INTERNAL_ERROR', message: 'Lỗi hệ thống' }
    renderPage()
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Xóa: MockBook Gaming 15' }))
    await userEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Xóa cảnh báo',
      }),
    )
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(await screen.findByRole('alert')).toHaveTextContent('Lỗi hệ thống')
    expect(screen.getByRole('link', { name: 'MockBook Gaming 15' })).toBeInTheDocument()
  })
})
