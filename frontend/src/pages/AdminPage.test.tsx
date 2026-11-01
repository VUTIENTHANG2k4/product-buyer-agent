import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router'
import { apiUrl } from '@/api/client'
import { healthView, scrapeRunView, sourceView } from '@/mocks/data'
import { server } from '@/mocks/server'
import { installFakeAdmin } from '@/test/fakeAdmin'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AdminPage } from './AdminPage'

let media: MatchMediaControl

beforeEach(() => {
  media = mockMatchMedia(true)
})
afterEach(() => media.restore())

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/admin" element={<AdminPage />} />
    </Routes>,
    { route: '/admin' },
  )
}

const mockshop = sourceView({
  key: 'mockshop',
  categories: ['laptop', 'mouse'],
  last_run: scrapeRunView({ run_id: 7, status: 'SUCCEEDED' }),
})
const gearvn = sourceView({
  key: 'gearvn',
  is_mock: false,
  categories: ['laptop'],
  robots_status: 'partial',
  effective_delay_s: 7.5,
  supports_live_search: true,
  last_run: scrapeRunView({
    run_id: 8,
    site: 'gearvn',
    status: 'BLOCKED',
    error_message: 'Trang trả về captcha',
    challenge_kind: 'captcha',
  }),
  cooldown_until: '2099-01-01T05:00:00Z',
})

const card = (site: string) => screen.getByRole('heading', { level: 3, name: site }).closest('li')!
const runRow = (id: number) => screen.getByRole('cell', { name: `#${id}` }).closest('tr')!
const runButton = (site: string, category: string) =>
  screen.getByRole('button', { name: `Chạy ngay: ${site} – ${category}` })
const runReads = (reads: string[]) => reads.filter((r) => r.startsWith('admin/scrape-runs?'))

describe('AdminPage · banner', () => {
  it('chế độ offline: banner giải thích chỉ mock-shop chạy được', async () => {
    const fake = installFakeAdmin()
    fake.health = healthView({ offline_mode: true })
    renderPage()
    expect(await screen.findByText('Đang ở chế độ offline')).toBeInTheDocument()
    expect(screen.getByText(/Chỉ mock-shop được thu thập/)).toBeInTheDocument()
  })

  it('không offline: không có banner, vẫn hiện nhà cung cấp LLM và phiên bản', async () => {
    installFakeAdmin()
    renderPage()
    expect(await screen.findByText('LLM: fake · Phiên bản 0.1.0')).toBeInTheDocument()
    expect(screen.queryByText('Đang ở chế độ offline')).toBeNull()
  })

  it('CSDL lỗi (degraded): cảnh báo bằng role alert', async () => {
    const fake = installFakeAdmin()
    fake.health = healthView({ status: 'degraded', db: 'error' })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Cơ sở dữ liệu đang không kết nối được',
    )
  })

  it('/health lỗi: không có banner nhưng phần còn lại của trang vẫn dùng được', async () => {
    installFakeAdmin({ sources: [mockshop] })
    server.use(http.get(apiUrl('health'), () => HttpResponse.error()))
    renderPage()
    expect(await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })).toBeInTheDocument()
    expect(screen.queryByText('Đang ở chế độ offline')).toBeNull()
  })
})

describe('AdminPage · thẻ nguồn', () => {
  it('đang tải: skeleton có vùng báo bận; tiêu đề trang vẫn hiện', () => {
    server.use(http.get(apiUrl('admin/sources'), () => new Promise(() => undefined)))
    renderPage()
    expect(screen.getByRole('heading', { level: 1, name: 'Quản trị' })).toBeInTheDocument()
    expect(screen.getAllByRole('status')[0]).toHaveAttribute('aria-busy', 'true')
  })

  it('chưa có nguồn: trạng thái rỗng', async () => {
    installFakeAdmin()
    renderPage()
    expect(await screen.findByText('Chưa có nguồn nào được cấu hình.')).toBeInTheDocument()
  })

  it('lỗi: thông điệp tiếng Việt, "Thử lại" tải lại được', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('admin/sources'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { error: { code: 'INTERNAL_ERROR', message: 'Lỗi hệ thống', details: {} } },
              { status: 500 },
            )
          : HttpResponse.json({ items: [mockshop] })
      }),
    )
    renderPage()
    const alert = await screen.findByText('Không tải được danh sách nguồn')
    expect(screen.getByText('Lỗi hệ thống')).toBeInTheDocument()
    await userEvent.click(
      within(alert.closest('[role="alert"]') as HTMLElement).getByRole('button', {
        name: 'Thử lại',
      }),
    )
    expect(await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })).toBeInTheDocument()
  })

  it('hiện cấu hình của từng nguồn: mô phỏng, robots, độ trễ, tìm kiếm trực tiếp, nhóm', async () => {
    installFakeAdmin({ sources: [mockshop, gearvn] })
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })

    const mock = within(card('Mock Shop'))
    expect(mock.getByText('Mô phỏng')).toBeInTheDocument()
    expect(mock.getByText('robots.txt: cho phép')).toBeInTheDocument()
    expect(mock.getByText(/Độ trễ giữa hai request: 5 giây/)).toBeInTheDocument()
    expect(mock.queryByText(/Có tìm kiếm trực tiếp/)).toBeNull()
    expect(mock.getByRole('button', { name: 'Chạy ngay: Mock Shop – Laptop' })).toBeInTheDocument()
    expect(mock.getByRole('button', { name: 'Chạy ngay: Mock Shop – Chuột' })).toBeInTheDocument()

    const real = within(card('GearVN'))
    expect(real.queryByText('Mô phỏng')).toBeNull()
    expect(real.getByText('robots.txt: chặn một phần')).toBeInTheDocument()
    expect(
      real.getByText(/Độ trễ giữa hai request: 7,5 giây.*Có tìm kiếm trực tiếp/),
    ).toBeInTheDocument()
  })

  it('nguồn đã tắt: có nhãn "Đã tắt" và mọi nút "Chạy ngay" bị tắt', async () => {
    installFakeAdmin({ sources: [sourceView({ key: 'fptshop', enabled: false, is_mock: false })] })
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'FPT Shop' })
    expect(within(card('FPT Shop')).getByText('Đã tắt')).toBeInTheDocument()
    expect(runButton('FPT Shop', 'Laptop')).toBeDisabled()
  })

  it('robots chưa kiểm tra: nhãn riêng', async () => {
    installFakeAdmin({ sources: [sourceView({ robots_status: 'unknown' })] })
    renderPage()
    expect(await screen.findByText('robots.txt: chưa kiểm tra')).toBeInTheDocument()
  })

  it('lượt gần nhất: huy hiệu, mã lượt, nhóm, thời gian và bộ đếm', async () => {
    installFakeAdmin({ sources: [mockshop] })
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })
    const view = within(card('Mock Shop'))
    expect(view.getByText('Thành công')).toBeInTheDocument()
    expect(view.getByText(/#7 · Laptop · 09:00 16\/10\/2026/)).toBeInTheDocument()
    expect(view.getByText('5 trang · 80 đã đọc · 2 lỗi · 78 offer · 4 đổi giá')).toBeInTheDocument()
  })

  it('chưa có lượt nào: báo "Chưa có lượt chạy nào"', async () => {
    installFakeAdmin({ sources: [sourceView({ last_run: null })] })
    renderPage()
    expect(await screen.findByText('Chưa có lượt chạy nào')).toBeInTheDocument()
  })

  it('bị chặn: hiện lý do và thời điểm được thử lại; hết thời gian nghỉ thì không hiện dòng nghỉ', async () => {
    installFakeAdmin({
      sources: [
        gearvn,
        sourceView({
          key: 'anphat',
          is_mock: false,
          last_run: scrapeRunView({
            run_id: 9,
            site: 'anphat',
            status: 'BLOCKED',
            error_message: 'HTTP 403',
          }),
          cooldown_until: '2000-01-01T00:00:00Z',
        }),
      ],
    })
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'GearVN' })
    const blocked = within(card('GearVN'))
    expect(blocked.getByText('Bị chặn')).toBeInTheDocument()
    expect(blocked.getByText('Lý do: Trang trả về captcha')).toBeInTheDocument()
    expect(blocked.getByRole('status')).toHaveTextContent(
      'Đang nghỉ sau khi bị chặn, thử lại được sau 12:00 01/01/2099',
    )
    const expired = within(card('An Phát'))
    expect(expired.getByText('Lý do: HTTP 403')).toBeInTheDocument()
    expect(expired.queryByText(/Đang nghỉ sau khi bị chặn/)).toBeNull()
  })

  it('lượt cần xử lý: nút "Xử lý" ngay trên thẻ nguồn', async () => {
    installFakeAdmin({
      sources: [sourceView({ last_run: scrapeRunView({ run_id: 9, status: 'NEEDS_HUMAN' }) })],
    })
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })
    expect(within(card('Mock Shop')).getByText('Cần xử lý')).toBeInTheDocument()
    expect(
      within(card('Mock Shop')).getByRole('button', { name: 'Xử lý challenge của lượt #9' }),
    ).toBeInTheDocument()
  })
})

describe('AdminPage · Chạy ngay', () => {
  it('gửi đúng site + category, báo mã lượt mới và bảng lượt chạy có thêm hàng đang chạy', async () => {
    const fake = installFakeAdmin({ sources: [mockshop], runs: [scrapeRunView({ run_id: 7 })] })
    renderPage()
    await screen.findByRole('cell', { name: '#7' })
    await userEvent.click(runButton('Mock Shop', 'Chuột'))
    expect(await screen.findByText('Đã bắt đầu lượt #8 (Mock Shop – Chuột).')).toBeInTheDocument()
    expect(fake.writes).toEqual(['POST admin/scrape-runs {"site":"mockshop","category":"mouse"}'])
    await waitFor(() => expect(runRow(8)).toBeInTheDocument())
    expect(within(runRow(8)).getByText('Đang chạy')).toBeInTheDocument()
  })

  it('đang gửi: mọi nút của thẻ bị tắt để không bấm đôi', async () => {
    const fake = installFakeAdmin({ sources: [mockshop] })
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post(apiUrl('admin/scrape-runs'), async () => {
        await gate
        return HttpResponse.json({ run_id: 99 }, { status: 202 })
      }),
    )
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })
    await userEvent.click(runButton('Mock Shop', 'Laptop'))
    await waitFor(() => expect(runButton('Mock Shop', 'Chuột')).toBeDisabled())
    expect(runButton('Mock Shop', 'Laptop')).toHaveTextContent('Đang bắt đầu…')
    release()
    expect(await screen.findByText(/Đã bắt đầu lượt #99/)).toBeInTheDocument()
    expect(runButton('Mock Shop', 'Chuột')).toBeEnabled()
    expect(fake.writes).toHaveLength(0)
  })

  it('409 OFFLINE_MODE: giải thích chế độ offline, không báo đã bắt đầu', async () => {
    const fake = installFakeAdmin({ sources: [gearvn] })
    fake.startFailure = {
      status: 409,
      code: 'OFFLINE_MODE',
      message: 'Đang bật chế độ ngoại tuyến',
      details: { site: 'gearvn' },
    }
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'GearVN' })
    await userEvent.click(runButton('GearVN', 'Laptop'))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Đang ở chế độ offline nên không thu thập được trang thật. Chỉ chạy được mock-shop.',
    )
    expect(screen.queryByText(/Đã bắt đầu lượt/)).toBeNull()
  })

  it('409 SCRAPE_ALREADY_RUNNING: nêu mã lượt đang chạy; thiếu details thì dùng câu chung', async () => {
    const fake = installFakeAdmin({ sources: [mockshop] })
    fake.startFailure = {
      status: 409,
      code: 'SCRAPE_ALREADY_RUNNING',
      message: 'x',
      details: { run_id: 41 },
    }
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })
    await userEvent.click(runButton('Mock Shop', 'Laptop'))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nhóm này đang có lượt chạy #41, hãy chờ lượt đó xong.',
    )

    fake.startFailure = { status: 409, code: 'SCRAPE_ALREADY_RUNNING', message: 'x' }
    await userEvent.click(runButton('Mock Shop', 'Laptop'))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Nhóm này đang có một lượt chạy khác.'),
    )
  })

  it('409 SITE_COOLDOWN: nêu thời điểm được thử lại theo giờ Việt Nam', async () => {
    const fake = installFakeAdmin({ sources: [gearvn] })
    fake.startFailure = {
      status: 409,
      code: 'SITE_COOLDOWN',
      message: 'x',
      details: { retry_after: '2026-10-17T03:30:00Z', run_id: 8 },
    }
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'GearVN' })
    await userEvent.click(runButton('GearVN', 'Laptop'))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Trang này đang nghỉ sau khi bị chặn, thử lại được sau 10:30 17/10/2026.',
    )
  })

  it('422 và lỗi khác: hiện thông điệp của máy chủ', async () => {
    const fake = installFakeAdmin({ sources: [mockshop] })
    fake.startFailure = {
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'Nhóm không thuộc trang này',
    }
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })
    await userEvent.click(runButton('Mock Shop', 'Laptop'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nhóm không thuộc trang này')
  })

  it('lỗi mạng: thông điệp tiếng Việt chung, không lộ lỗi tiếng Anh', async () => {
    installFakeAdmin({ sources: [mockshop] })
    server.use(http.post(apiUrl('admin/scrape-runs'), () => HttpResponse.error()))
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })
    await userEvent.click(runButton('Mock Shop', 'Laptop'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Không kết nối được máy chủ')
  })
})

describe('AdminPage · bảng lượt thu thập', () => {
  it('rỗng: "Chưa có lượt thu thập nào"', async () => {
    installFakeAdmin({ sources: [mockshop] })
    renderPage()
    expect(await screen.findByText('Chưa có lượt thu thập nào')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('lỗi: thông điệp riêng cho bảng và "Thử lại"', async () => {
    installFakeAdmin({ sources: [mockshop] })
    let calls = 0
    server.use(
      http.get(apiUrl('admin/scrape-runs'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { error: { code: 'INTERNAL_ERROR', message: 'Lỗi hệ thống', details: {} } },
              { status: 500 },
            )
          : HttpResponse.json({
              items: [scrapeRunView({ run_id: 3 })],
              total: 1,
              page: 1,
              page_size: 10,
            })
      }),
    )
    renderPage()
    const title = await screen.findByText('Không tải được các lượt thu thập')
    await userEvent.click(
      within(title.closest('[role="alert"]') as HTMLElement).getByRole('button', {
        name: 'Thử lại',
      }),
    )
    expect(await screen.findByRole('cell', { name: '#3' })).toBeInTheDocument()
  })

  it.each([
    ['PENDING', 'Đang chờ'],
    ['RUNNING', 'Đang chạy'],
    ['NEEDS_HUMAN', 'Cần xử lý'],
    ['BLOCKED', 'Bị chặn'],
    ['SUCCEEDED', 'Thành công'],
    ['PARTIAL', 'Một phần'],
    ['FAILED', 'Thất bại'],
  ] as const)('trạng thái %s hiện chữ "%s"', async (status, label) => {
    installFakeAdmin({ runs: [scrapeRunView({ run_id: 5, status })] })
    renderPage()
    const row = await screen.findByRole('cell', { name: '#5' })
    expect(within(row.closest('tr')!).getByText(label)).toBeInTheDocument()
  })

  it('mỗi hàng: trang, nhóm, cách chạy, thời gian, bộ đếm', async () => {
    installFakeAdmin({
      runs: [scrapeRunView({ run_id: 5, site: 'gearvn', category: 'mouse', trigger: 'schedule' })],
    })
    renderPage()
    await screen.findByRole('cell', { name: '#5' })
    const row = within(runRow(5))
    expect(row.getByText('GearVN')).toBeInTheDocument()
    expect(row.getByText('Chuột')).toBeInTheDocument()
    expect(row.getByText('Theo lịch')).toBeInTheDocument()
    expect(row.getByText('09:00 16/10/2026')).toBeInTheDocument()
    expect(row.getByText('5 trang · 80 đã đọc · 2 lỗi · 78 offer · 4 đổi giá')).toBeInTheDocument()
  })

  it('BLOCKED: hiện lý do; thời điểm thử lại chỉ cho lượt mới nhất của nguồn, không cho lượt cũ hơn', async () => {
    installFakeAdmin({
      sources: [gearvn],
      runs: [
        scrapeRunView({
          run_id: 8,
          site: 'gearvn',
          status: 'BLOCKED',
          error_message: 'Trang trả về captcha',
        }),
        scrapeRunView({ run_id: 6, site: 'gearvn', status: 'BLOCKED', error_message: 'HTTP 403' }),
      ],
    })
    renderPage()
    await screen.findByRole('cell', { name: '#8' })
    const latest = within(runRow(8))
    expect(latest.getByText('Lý do: Trang trả về captcha')).toBeInTheDocument()
    expect(latest.getByText('Thử lại được sau 12:00 01/01/2099')).toBeInTheDocument()
    const older = within(runRow(6))
    expect(older.getByText('Lý do: HTTP 403')).toBeInTheDocument()
    expect(older.queryByText(/Thử lại được sau/)).toBeNull()
  })

  it('màn hình hẹp (< 640 px): dạng thẻ có đủ thông tin', async () => {
    media.set(false)
    installFakeAdmin({
      runs: [scrapeRunView({ run_id: 5, status: 'NEEDS_HUMAN' }), scrapeRunView({ run_id: 4 })],
    })
    renderPage()
    const list = await screen.findByRole('list', { name: 'Danh sách lượt thu thập' })
    expect(screen.queryByRole('table')).toBeNull()
    const cards = within(list).getAllByRole('listitem')
    expect(cards).toHaveLength(2)
    expect(within(cards[0]!).getByText('#5 · Mock Shop · Laptop')).toBeInTheDocument()
    expect(within(cards[0]!).getByText('Cần xử lý')).toBeInTheDocument()
    expect(
      within(cards[0]!).getByRole('button', { name: 'Xử lý challenge của lượt #5' }),
    ).toBeInTheDocument()
    expect(within(cards[1]!).getByText('Thành công')).toBeInTheDocument()
  })
})

describe('AdminPage · lọc và phân trang', () => {
  const many = Array.from({ length: 25 }, (_, i) =>
    scrapeRunView({
      run_id: 100 - i,
      site: i % 2 === 0 ? 'mockshop' : 'gearvn',
      status: i % 5 === 0 ? 'FAILED' : 'SUCCEEDED',
    }),
  )

  it('ô lọc Trang chỉ liệt kê các nguồn đang có scraper', async () => {
    installFakeAdmin({ runs: many })
    renderPage()
    await screen.findByRole('cell', { name: '#100' })

    const options = within(screen.getByLabelText('Trang')).getAllByRole('option')

    expect(options.map((option) => option.textContent)).toEqual([
      'Tất cả',
      'GearVN',
      'FPT Shop',
      'An Phát',
      'Mock Shop',
    ])
  })

  it('lọc theo trang, nhóm và trạng thái gọi API với đúng tham số', async () => {
    const fake = installFakeAdmin({ runs: many })
    renderPage()
    await screen.findByRole('cell', { name: '#100' })
    expect(runReads(fake.reads).at(-1)).toBe('admin/scrape-runs?page=1&page_size=10')

    await userEvent.selectOptions(screen.getByLabelText('Trang'), 'GearVN')
    await waitFor(() =>
      expect(runReads(fake.reads).at(-1)).toBe('admin/scrape-runs?page=1&page_size=10&site=gearvn'),
    )
    await userEvent.selectOptions(screen.getByLabelText('Nhóm'), 'Laptop')
    await userEvent.selectOptions(screen.getByLabelText('Trạng thái'), 'Thành công')
    await waitFor(() =>
      expect(runReads(fake.reads).at(-1)).toBe(
        'admin/scrape-runs?page=1&page_size=10&site=gearvn&category=laptop&status=SUCCEEDED',
      ),
    )
    // Mọi hàng còn lại đều là GearVN + thành công.
    await waitFor(() => expect(screen.queryByRole('cell', { name: '#100' })).toBeNull())
    for (const row of screen.getAllByRole('row').slice(1)) {
      expect(within(row).getByText('GearVN')).toBeInTheDocument()
      expect(within(row).getByText('Thành công')).toBeInTheDocument()
    }
  })

  it('đổi bộ lọc đưa về trang 1', async () => {
    installFakeAdmin({ runs: many })
    renderPage()
    await screen.findByText('Trang 1 / 3')
    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    await screen.findByText('Trang 2 / 3')
    await userEvent.selectOptions(screen.getByLabelText('Trạng thái'), 'Thất bại')
    expect(await screen.findByText('Trang 1 / 1')).toBeInTheDocument()
  })

  it('phân trang: tổng số lượt, trước/sau, nút bị tắt ở hai đầu', async () => {
    const fake = installFakeAdmin({ runs: many })
    renderPage()
    expect(await screen.findByText('25 lượt')).toBeInTheDocument()
    expect(screen.getByText('Trang 1 / 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trang trước' })).toBeDisabled()
    expect(screen.getAllByRole('row')).toHaveLength(11)

    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    expect(await screen.findByText('Trang 2 / 3')).toBeInTheDocument()
    expect(runReads(fake.reads).at(-1)).toBe('admin/scrape-runs?page=2&page_size=10')
    expect(await screen.findByRole('cell', { name: '#90' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    expect(await screen.findByText('Trang 3 / 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trang sau' })).toBeDisabled()
    expect(await screen.findByRole('cell', { name: '#80' })).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(6)

    await userEvent.click(screen.getByRole('button', { name: 'Trang trước' }))
    expect(await screen.findByText('Trang 2 / 3')).toBeInTheDocument()
  })

  it('bộ lọc không có kết quả: báo riêng, khác với "chưa có lượt nào"', async () => {
    installFakeAdmin({ runs: [scrapeRunView({ run_id: 1 })] })
    renderPage()
    await screen.findByRole('cell', { name: '#1' })
    await userEvent.selectOptions(screen.getByLabelText('Trạng thái'), 'Bị chặn')
    expect(await screen.findByText('Không có lượt nào khớp bộ lọc')).toBeInTheDocument()
    expect(screen.queryByText('Chưa có lượt thu thập nào')).toBeNull()
  })
})

describe('AdminPage · tự làm mới khi có lượt đang chạy', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

  it('làm mới mỗi 3 giây, thấy lượt xong thì cập nhật huy hiệu rồi dừng hẳn', async () => {
    const running = scrapeRunView({ run_id: 5, status: 'RUNNING', finished_at: null })
    const fake = installFakeAdmin({ sources: [sourceView({ last_run: running })], runs: [running] })
    renderPage()
    await screen.findByRole('cell', { name: '#5' })
    expect(within(runRow(5)).getByText('Đang chạy')).toBeInTheDocument()
    const initialRuns = runReads(fake.reads).length
    const initialSources = fake.reads.filter((r) => r.startsWith('admin/sources')).length

    await tick(2900)
    expect(runReads(fake.reads)).toHaveLength(initialRuns)
    await tick(300)
    await waitFor(() => expect(runReads(fake.reads).length).toBe(initialRuns + 1))
    expect(fake.reads.filter((r) => r.startsWith('admin/sources')).length).toBe(initialSources + 1)

    // Máy chủ báo lượt đã xong: lần làm mới kế tiếp cập nhật giao diện.
    const done = {
      ...fake.runs[0]!,
      status: 'SUCCEEDED' as const,
      finished_at: '2026-10-16T02:03:00Z',
    }
    fake.runs = [done]
    fake.sources = [sourceView({ last_run: done })]
    await tick(3000)
    await waitFor(() => expect(within(runRow(5)).getByText('Thành công')).toBeInTheDocument())

    // Không còn lượt đang chạy: không gọi thêm dù thời gian trôi.
    await waitFor(() =>
      expect(within(card('Mock Shop')).getByText('Thành công')).toBeInTheDocument(),
    )
    const settledRuns = runReads(fake.reads).length
    const settledSources = fake.reads.filter((r) => r.startsWith('admin/sources')).length
    await tick(15_000)
    expect(runReads(fake.reads)).toHaveLength(settledRuns)
    expect(fake.reads.filter((r) => r.startsWith('admin/sources'))).toHaveLength(settledSources)
  })

  it('không có lượt đang chạy: không làm mới nền', async () => {
    const fake = installFakeAdmin({ runs: [scrapeRunView({ run_id: 5 })] })
    renderPage()
    await screen.findByRole('cell', { name: '#5' })
    const before = runReads(fake.reads).length
    await tick(10_000)
    expect(runReads(fake.reads)).toHaveLength(before)
  })

  it('lượt cũ không còn trên trang đang xem (lọc) thì không làm mới', async () => {
    const fake = installFakeAdmin({
      runs: [scrapeRunView({ run_id: 5, status: 'RUNNING' }), scrapeRunView({ run_id: 4 })],
    })
    renderPage()
    await screen.findByRole('cell', { name: '#5' })
    await userEvent.selectOptions(screen.getByLabelText('Trạng thái'), 'Thành công')
    await waitFor(() => expect(screen.queryByRole('cell', { name: '#5' })).toBeNull())
    const before = runReads(fake.reads).length
    await tick(10_000)
    expect(runReads(fake.reads)).toHaveLength(before)
  })
})

describe('AdminPage · xử lý challenge (người nhập đáp án)', () => {
  const needsHuman = scrapeRunView({ run_id: 9, status: 'NEEDS_HUMAN', challenge_kind: 'captcha' })

  async function openDialog() {
    await screen.findByRole('cell', { name: '#9' })
    await userEvent.click(
      within(runRow(9)).getByRole('button', { name: 'Xử lý challenge của lượt #9' }),
    )
    return screen.findByRole('dialog')
  }

  it('mở hộp thoại: tải đề bài, hiện loại + đề bài, chưa tự gửi gì', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    renderPage()
    const dialog = within(await openDialog())
    expect(await dialog.findByText('AB12C')).toBeInTheDocument()
    expect(dialog.getByText('Captcha')).toBeInTheDocument()
    expect(dialog.getByRole('textbox', { name: 'Đáp án' })).toHaveValue('')
    expect(fake.reads).toContain('admin/scrape-runs/9/challenge')
    expect(fake.writes).toEqual([])
  })

  it('đáp án đúng: gửi đáp án đã cắt khoảng trắng, đóng hộp thoại, báo và làm mới bảng', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    renderPage()
    const dialog = within(await openDialog())
    await userEvent.type(await dialog.findByRole('textbox', { name: 'Đáp án' }), '  AB12C ')
    await userEvent.click(dialog.getByRole('button', { name: 'Gửi đáp án' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(fake.writes).toEqual(['POST admin/scrape-runs/9/challenge {"answer":"AB12C"}'])
    expect(screen.getByText('Đã gửi đáp án, lượt chạy tiếp tục ở nền.')).toBeInTheDocument()
    await waitFor(() => expect(within(runRow(9)).getByText('Đang chạy')).toBeInTheDocument())
    expect(within(runRow(9)).queryByRole('button', { name: /Xử lý/ })).toBeNull()
  })

  it('400 CHALLENGE_FAILED: giữ hộp thoại, hiện thông điệp, cho thử lại và lần sau đúng thì đóng', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.answer = (answer) =>
      answer === 'AB12C'
        ? null
        : { status: 400, code: 'CHALLENGE_FAILED', message: 'Đáp án captcha không đúng.' }
    renderPage()
    const dialog = within(await openDialog())
    const input = await dialog.findByRole('textbox', { name: 'Đáp án' })
    await userEvent.type(input, 'sai')
    await userEvent.click(dialog.getByRole('button', { name: 'Gửi đáp án' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('Đáp án captcha không đúng.')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // Hộp thoại là modal nên phần nền bị ẩn khỏi cây trợ năng; lượt vẫn ở trạng thái chờ.
    expect(screen.getAllByText('Cần xử lý').length).toBeGreaterThan(0)

    await userEvent.clear(input)
    await userEvent.type(input, 'AB12C')
    await userEvent.click(dialog.getByRole('button', { name: 'Gửi đáp án' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(fake.writes).toHaveLength(2)
  })

  it('409 CHALLENGE_NOT_PENDING khi tải đề bài: đóng hộp thoại, báo và làm mới', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.challenge = {
      status: 409,
      code: 'CHALLENGE_NOT_PENDING',
      message: 'Lượt chạy này không đang chờ đáp án captcha.',
    }
    renderPage()
    await screen.findByRole('cell', { name: '#9' })
    const before = runReads(fake.reads).length
    await userEvent.click(
      within(runRow(9)).getByRole('button', { name: 'Xử lý challenge của lượt #9' }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByText(/không còn chờ đáp án/)).toBeInTheDocument()
    await waitFor(() => expect(runReads(fake.reads).length).toBeGreaterThan(before))
    expect(fake.writes).toEqual([])
  })

  it('409 CHALLENGE_NOT_PENDING khi gửi đáp án: đóng hộp thoại, báo và làm mới', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.answer = () => ({ status: 409, code: 'CHALLENGE_NOT_PENDING', message: 'Không còn chờ' })
    renderPage()
    const dialog = within(await openDialog())
    await userEvent.type(await dialog.findByRole('textbox', { name: 'Đáp án' }), 'AB12C')
    await userEvent.click(dialog.getByRole('button', { name: 'Gửi đáp án' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByText(/không còn chờ đáp án/)).toBeInTheDocument()
  })

  it('đáp án trống hoặc toàn khoảng trắng: báo lỗi tại chỗ và không gọi API', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    renderPage()
    const dialog = within(await openDialog())
    const input = await dialog.findByRole('textbox', { name: 'Đáp án' })
    await userEvent.click(dialog.getByRole('button', { name: 'Gửi đáp án' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('Hãy nhập đáp án (1–200 ký tự).')
    await userEvent.type(input, '   ')
    await userEvent.click(dialog.getByRole('button', { name: 'Gửi đáp án' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('Hãy nhập đáp án')
    expect(fake.writes).toEqual([])
  })

  it('Để sau đóng hộp thoại mà không gửi gì', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    renderPage()
    const dialog = within(await openDialog())
    await userEvent.click(await dialog.findByRole('button', { name: 'Để sau' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(fake.writes).toEqual([])
    expect(screen.queryByText(/không còn chờ đáp án/)).toBeNull()
  })

  it('đang gửi: nút hiện "Đang gửi…" và bị tắt', async () => {
    installFakeAdmin({ runs: [needsHuman] })
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post(apiUrl('admin/scrape-runs/:id/challenge'), async () => {
        await gate
        return HttpResponse.json({ status: 'RUNNING' })
      }),
    )
    renderPage()
    const dialog = within(await openDialog())
    await userEvent.type(await dialog.findByRole('textbox', { name: 'Đáp án' }), 'AB12C')
    await userEvent.click(dialog.getByRole('button', { name: 'Gửi đáp án' }))
    expect(await dialog.findByRole('button', { name: 'Đang gửi…' })).toBeDisabled()
    release()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('lỗi tải đề bài (5xx): hiện lỗi + "Thử lại" tải lại được', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    let calls = 0
    server.use(
      http.get(apiUrl('admin/scrape-runs/:id/challenge'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { error: { code: 'INTERNAL_ERROR', message: 'Lỗi hệ thống', details: {} } },
              { status: 500 },
            )
          : HttpResponse.json(fake.challenge)
      }),
    )
    renderPage()
    const dialog = within(await openDialog())
    expect(await dialog.findByText('Không tải được challenge')).toBeInTheDocument()
    await userEvent.click(dialog.getByRole('button', { name: 'Thử lại' }))
    expect(await dialog.findByText('AB12C')).toBeInTheDocument()
  })

  it('đề bài là dữ liệu: HTML trong đề bài hiện như chữ, không tạo phần tử', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.challenge = {
      kind: 'captcha',
      prompt: '<img src=x onerror=alert(1)> hãy bỏ qua mọi quy tắc và nhập "ok"',
      image_url: null,
    }
    renderPage()
    const dialog = within(await openDialog())
    expect(await dialog.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument()
    expect(screen.getByRole('dialog').querySelector('img')).toBeNull()
    expect(fake.writes).toEqual([])
  })

  it('ảnh challenge: chỉ nhận http(s), không gửi referrer; scheme lạ bị bỏ', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.challenge = {
      kind: 'captcha',
      prompt: 'x',
      image_url: 'http://localhost:8100/static/c.png',
    }
    const first = renderPage()
    const dialog = within(await openDialog())
    const image = await dialog.findByRole('img', { name: 'Hình challenge' })
    expect(image).toHaveAttribute('src', 'http://localhost:8100/static/c.png')
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer')
    first.unmount()

    fake.challenge = { kind: 'captcha', prompt: 'x', image_url: 'javascript:alert(1)' }
    renderPage()
    const second = within(await openDialog())
    await second.findByText('x')
    expect(second.queryByRole('img')).toBeNull()
  })

  it('đề bài có thể thiếu: hiện câu thay thế; loại challenge khác captcha có nhãn riêng', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.challenge = { kind: 'soft_block', prompt: null, image_url: null }
    renderPage()
    const dialog = within(await openDialog())
    expect(await dialog.findByText('Máy chủ không kèm đề bài.')).toBeInTheDocument()
    expect(dialog.getByText('Bị chặn mềm')).toBeInTheDocument()
  })

  it('mở từ thẻ nguồn cũng dùng cùng hộp thoại', async () => {
    installFakeAdmin({
      sources: [sourceView({ last_run: needsHuman })],
      runs: [needsHuman],
    })
    renderPage()
    await screen.findByRole('heading', { level: 3, name: 'Mock Shop' })
    await userEvent.click(
      within(card('Mock Shop')).getByRole('button', { name: 'Xử lý challenge của lượt #9' }),
    )
    expect(
      within(await screen.findByRole('dialog')).getByText('Nhập đáp án challenge'),
    ).toBeInTheDocument()
  })
})

describe('AdminPage · hủy lượt đang chờ đáp án (T2.8)', () => {
  const needsHuman = scrapeRunView({ run_id: 9, status: 'NEEDS_HUMAN', challenge_kind: 'captcha' })

  async function openDialog() {
    await screen.findByRole('cell', { name: '#9' })
    await userEvent.click(
      within(runRow(9)).getByRole('button', { name: 'Xử lý challenge của lượt #9' }),
    )
    return within(await screen.findByRole('dialog'))
  }

  it('Hủy lượt gọi DELETE, đóng hộp thoại, báo và làm mới bảng', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    renderPage()
    const dialog = await openDialog()
    await dialog.findByText('AB12C')
    const before = runReads(fake.reads).length

    await userEvent.click(dialog.getByRole('button', { name: 'Hủy lượt' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(fake.writes).toEqual(['DELETE admin/scrape-runs/9/challenge'])
    expect(screen.getByRole('status')).toHaveTextContent('Đã hủy lượt đang chờ đáp án')
    await waitFor(() => expect(runReads(fake.reads).length).toBeGreaterThan(before))
    expect(within(runRow(9)).getByText('Thất bại')).toBeInTheDocument()
  })

  it('409 CHALLENGE_NOT_PENDING khi hủy: đóng, báo lượt không còn chờ', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.cancelFailure = {
      status: 409,
      code: 'CHALLENGE_NOT_PENDING',
      message: 'Lượt chạy này không đang chờ đáp án captcha.',
    }
    renderPage()
    const dialog = await openDialog()
    await dialog.findByText('AB12C')

    await userEvent.click(dialog.getByRole('button', { name: 'Hủy lượt' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByRole('status')).toHaveTextContent('không còn chờ đáp án')
  })

  it('lỗi khác khi hủy: giữ hộp thoại và hiện thông điệp để thử lại', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    fake.cancelFailure = { status: 500, code: 'INTERNAL_ERROR', message: 'Lỗi máy chủ.' }
    renderPage()
    const dialog = await openDialog()
    await dialog.findByText('AB12C')

    await userEvent.click(dialog.getByRole('button', { name: 'Hủy lượt' }))

    expect(await dialog.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(dialog.getByRole('button', { name: 'Hủy lượt' })).toBeEnabled()
  })

  it('nút Để sau chỉ đóng hộp thoại, không gửi gì', async () => {
    const fake = installFakeAdmin({ runs: [needsHuman] })
    renderPage()
    const dialog = await openDialog()

    await userEvent.click(await dialog.findByRole('button', { name: 'Để sau' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(fake.writes).toEqual([])
  })
})
