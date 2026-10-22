import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Link, Route, Routes, useLocation } from 'react-router'
import { apiUrl } from '@/api/client'
import { offerView, productFull } from '@/mocks/data'
import { server } from '@/mocks/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ProductDetailPage } from './ProductDetailPage'

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function renderAt(route: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<Link to="/products/12">Tới sản phẩm</Link>} />
        <Route path="/products/:id" element={<ProductDetailPage />} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}

function product(over: Record<string, unknown> = {}) {
  server.use(http.get(apiUrl('products/12'), () => HttpResponse.json(productFull(over))))
}

function history(series: unknown[] = [], onRequest?: (days: string | null) => void) {
  server.use(
    http.get(apiUrl('products/12/price-history'), ({ request }) => {
      onRequest?.(new URL(request.url).searchParams.get('days'))
      return HttpResponse.json({ series, min_price: null, max_price: null })
    }),
  )
}

const pt = (t: string, price: number) => ({ t, price, price_type: 'regular' })
const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString()

describe('ProductDetailPage · nội dung', () => {
  it('đang tải: skeleton và đúng một h1 ẩn; xong: tên sản phẩm là h1', async () => {
    product({ name: 'MockBook Gaming 15' })
    renderAt('/products/12')
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    const heading = await screen.findByRole('heading', { level: 1, name: 'MockBook Gaming 15' })
    expect(heading).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('hiện hãng, mã model và khoảng giá khi giá thấp nhất khác cao nhất', async () => {
    product({
      brand: 'MockBrand',
      model_code: 'MG15-4060',
      min_price: 27_490_000,
      max_price: 29_990_000,
    })
    renderAt('/products/12')
    await screen.findByRole('heading', { level: 1, name: /MockBook/ })
    expect(screen.getByText('MockBrand · Mã: MG15-4060')).toBeInTheDocument()
    expect(screen.getByText('27.490.000 ₫ – 29.990.000 ₫')).toBeInTheDocument()
  })

  it('giá thấp nhất bằng cao nhất: hiện một giá; chưa có giá: không hiện dòng giá', async () => {
    product({ min_price: 27_490_000, max_price: 27_490_000 })
    const first = renderAt('/products/12')
    await screen.findByRole('heading', { level: 1, name: /MockBook/ })
    expect(screen.queryByText(/–/)).toBeNull()
    first.unmount()

    product({ min_price: null, max_price: null, offers: [] })
    renderAt('/products/12')
    await screen.findByRole('heading', { level: 1, name: /MockBook/ })
    expect(screen.queryByText(/₫ –/)).toBeNull()
  })

  it('bảng giá theo trang: rẻ nhất lên đầu, loại giá, tình trạng, giá niêm yết, liên kết an toàn', async () => {
    product({
      offers: [
        offerView({
          offer_id: 1,
          site: 'fptshop',
          price: 29_990_000,
          effective_price: 29_990_000,
          list_price: null,
          price_type: 'regular',
          stock_status: 'out_of_stock',
          url: 'https://mock-fpt.example/p/12',
        }),
        offerView({
          offer_id: 2,
          site: 'gearvn',
          price: 27_990_000,
          effective_price: 27_490_000,
          list_price: 29_990_000,
          price_type: 'member',
          stock_status: 'in_stock',
          url: 'https://mock-gearvn.example/p/12',
        }),
        offerView({ offer_id: 3, site: 'anphat', url: 'javascript:alert(1)' }),
      ],
    })
    renderAt('/products/12')
    const table = await screen.findByRole('table', { name: 'Giá theo trang' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0] as HTMLElement).getByText('GearVN')).toBeInTheDocument()
    expect(within(rows[0] as HTMLElement).getByText('27.490.000 ₫')).toBeInTheDocument()
    expect(
      within(rows[0] as HTMLElement).getByText('giá niêm yết 29.990.000 ₫'),
    ).toBeInTheDocument()
    expect(within(rows[0] as HTMLElement).getByText('Thành viên')).toBeInTheDocument()
    expect(within(rows[0] as HTMLElement).getByText('Rẻ nhất')).toBeInTheDocument()
    expect(within(table).getByText('Hết hàng')).toBeInTheDocument()
    expect(within(table).getByText('Giá thường')).toBeInTheDocument()

    const link = within(table).getByRole('link', { name: 'Mở trang GearVN' })
    expect(link).toHaveAttribute('href', 'https://mock-gearvn.example/p/12')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    // Offer có URL nguy hiểm không có liên kết.
    expect(within(table).getAllByRole('link', { name: /Mở trang/ })).toHaveLength(2)
  })

  it('offer cũ hơn 24 giờ hiện badge vàng "Giá cập nhật lúc"', async () => {
    product({ offers: [offerView({ scraped_at: hoursAgo(72) })] })
    renderAt('/products/12')
    expect(
      await screen.findByText(/^Giá cập nhật lúc \d{2}:\d{2} \d{2}\/\d{2}$/),
    ).toBeInTheDocument()
  })

  it('offer mới chỉ hiện giờ cập nhật, không có badge vàng', async () => {
    product({ offers: [offerView({ scraped_at: hoursAgo(1) })] })
    renderAt('/products/12')
    await screen.findByRole('table', { name: 'Giá theo trang' })
    expect(screen.queryByText(/^Giá cập nhật lúc/)).toBeNull()
  })

  it('không có offer nào: giải thích thay vì bảng trống', async () => {
    product({ offers: [], min_price: null, max_price: null })
    renderAt('/products/12')
    expect(await screen.findByText('Chưa có trang nào đang bán sản phẩm này.')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Giá theo trang' })).toBeNull()
  })
})

describe('ProductDetailPage · thông số', () => {
  it('bảng thông số có nhãn tiếng Việt, đơn vị, và ẩn hạng GPU suy ra', async () => {
    product({
      specs: {
        cpu_model: 'i7-13620H',
        gpu_model: 'RTX 4060',
        gpu_rank: 40,
        ram_gb: 16,
        storage_gb: 1000,
      },
    })
    renderAt('/products/12')
    const table = await screen.findByRole('table', { name: 'Thông số' })
    expect(within(table).getByRole('rowheader', { name: 'RAM' })).toBeInTheDocument()
    expect(within(table).getByText('16 GB')).toBeInTheDocument()
    expect(within(table).getByText('1 TB')).toBeInTheDocument()
    expect(within(table).queryByRole('rowheader', { name: 'Hạng GPU' })).toBeNull()
  })

  it('không có thông số: hiện trạng thái rỗng', async () => {
    product({ specs: {} })
    renderAt('/products/12')
    expect(
      await screen.findByText('Chưa có thông số chuẩn hóa cho sản phẩm này.'),
    ).toBeInTheDocument()
  })

  it.each([
    [0.79, true],
    [0.5, true],
    [0, true],
    [0.8, false],
    [1, false],
  ])('độ tin cậy %s → thông báo "trích tự động" %s', async (confidence, shown) => {
    product({ specs_confidence: confidence })
    renderAt('/products/12')
    await screen.findByRole('table', { name: 'Thông số' })
    const note = screen.queryByRole('note')
    if (shown) {
      expect(note).toHaveTextContent(
        'Một số thông số được trích tự động, hãy kiểm tra trên trang bán.',
      )
    } else {
      expect(note).toBeNull()
    }
  })
})

describe('ProductDetailPage · lỗi và điều hướng', () => {
  it('404: hiện thông điệp của API, vẫn có h1 và nút Quay lại', async () => {
    server.use(
      http.get(apiUrl('products/12'), () =>
        HttpResponse.json(
          {
            error: {
              code: 'PRODUCT_NOT_FOUND',
              message: 'Không tìm thấy sản phẩm 12',
              details: {},
            },
          },
          { status: 404 },
        ),
      ),
    )
    renderAt('/products/12')
    expect(await screen.findByRole('alert')).toHaveTextContent('Không tìm thấy sản phẩm 12')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Quay lại' })).toBeInTheDocument()
  })

  it('lỗi mạng rồi "Thử lại" thành công', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('products/12'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.error()
          : HttpResponse.json(productFull({ name: 'MockBook Sau Retry' }))
      }),
    )
    renderAt('/products/12')
    await userEvent.click(await screen.findByRole('button', { name: 'Thử lại' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: 'MockBook Sau Retry' }),
    ).toBeInTheDocument()
  })

  it.each(['abc', '0', '-1', '1.5', '2147483648', '%3Cscript%3E'])(
    'mã %s không hợp lệ: báo ngay, không gọi API sản phẩm',
    (id) => {
      let calls = 0
      server.use(
        http.get(apiUrl('products/:id'), () => {
          calls += 1
          return HttpResponse.json(productFull())
        }),
      )
      renderAt(`/products/${id}`)
      expect(screen.getByRole('alert')).toHaveTextContent('Mã sản phẩm không hợp lệ.')
      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
      expect(calls).toBe(0)
    },
  )

  it('mở thẳng đường dẫn (không có lịch sử): Quay lại đưa về trang chính', async () => {
    product()
    renderAt('/products/12')
    await screen.findByRole('heading', { level: 1, name: /MockBook/ })
    await userEvent.click(screen.getByRole('button', { name: 'Quay lại' }))
    expect(screen.getByTestId('where')).toHaveTextContent('/')
    expect(screen.getByRole('link', { name: 'Tới sản phẩm' })).toBeInTheDocument()
  })

  it('đi từ trang khác vào: Quay lại trở về đúng trang trước', async () => {
    product()
    renderAt('/')
    await userEvent.click(screen.getByRole('link', { name: 'Tới sản phẩm' }))
    await screen.findByRole('heading', { level: 1, name: /MockBook/ })
    expect(screen.getByTestId('where')).toHaveTextContent('/products/12')
    await userEvent.click(screen.getByRole('button', { name: 'Quay lại' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/$/))
  })
})

describe('ProductDetailPage · hành động', () => {
  it('"Thêm vào danh sách" mở hộp thoại cho đúng sản phẩm', async () => {
    product({ name: 'MockBook Gaming 15' })
    renderAt('/products/12')
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm vào danh sách' }))
    expect(await screen.findByRole('dialog', { name: 'Thêm vào danh sách mua' })).toHaveTextContent(
      'MockBook Gaming 15',
    )
  })

  it('"Báo khi giảm giá" mở hộp thoại kèm giá thấp nhất hiện tại', async () => {
    product({ min_price: 27_490_000 })
    renderAt('/products/12')
    await userEvent.click(await screen.findByRole('button', { name: 'Báo khi giảm giá' }))
    expect(await screen.findByRole('dialog', { name: 'Báo khi giảm giá' })).toHaveTextContent(
      'Giá thấp nhất hiện tại: 27.490.000 ₫',
    )
  })
})

describe('ProductDetailPage · lịch sử giá', () => {
  it('mặc định 30 ngày; đổi tab gọi lại API với đúng số ngày', async () => {
    product()
    const requested: (string | null)[] = []
    history([], (days) => requested.push(days))
    renderAt('/products/12')

    const tablist = await screen.findByRole('tablist', { name: 'Khoảng thời gian' })
    expect(within(tablist).getByRole('tab', { name: '30 ngày' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await waitFor(() => expect(requested).toEqual(['30']))

    await userEvent.click(within(tablist).getByRole('tab', { name: '7 ngày' }))
    await waitFor(() => expect(requested).toContain('7'))
    await userEvent.click(within(tablist).getByRole('tab', { name: '90 ngày' }))
    await waitFor(() => expect(requested).toContain('90'))
    expect(within(tablist).getByRole('tab', { name: '90 ngày' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('có dữ liệu: biểu đồ có mô tả cho trình đọc màn hình và bản tóm tắt theo từng trang', async () => {
    product()
    history([
      {
        site: 'gearvn',
        points: [pt('2026-10-01T00:00:00Z', 29_000_000), pt('2026-10-03T00:00:00Z', 27_500_000)],
      },
      { site: 'fptshop', points: [pt('2026-10-02T00:00:00Z', 28_500_000)] },
    ])
    renderAt('/products/12')
    const chart = await screen.findByRole('img', {
      name: /Biểu đồ giá 30 ngày gần nhất của GearVN, FPT Shop/,
    })
    expect(chart).toBeInTheDocument()
    expect(screen.getByText('GearVN:')).toBeInTheDocument()
    expect(
      screen.getByText('thấp nhất 27.500.000 ₫, cao nhất 29.000.000 ₫, mới nhất 27.500.000 ₫'),
    ).toBeInTheDocument()
    expect(screen.getByText('FPT Shop:')).toBeInTheDocument()
  })

  it('chưa có lịch sử: trạng thái rỗng có giải thích', async () => {
    product()
    history([])
    renderAt('/products/12')
    expect(await screen.findByText('Chưa có lịch sử giá')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /Biểu đồ giá/ })).toBeNull()
  })

  it('lỗi tải lịch sử không làm mất phần còn lại của trang', async () => {
    product({ name: 'MockBook Còn Đó' })
    server.use(http.get(apiUrl('products/12/price-history'), () => HttpResponse.error()))
    renderAt('/products/12')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Không tải được lịch sử giá')
    expect(screen.getByRole('heading', { level: 1, name: 'MockBook Còn Đó' })).toBeInTheDocument()
    expect(within(alert).getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
  })
})
