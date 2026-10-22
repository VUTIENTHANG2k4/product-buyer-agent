import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { listSummary, productRow, rowOffer } from '@/mocks/data'
import { server } from '@/mocks/server'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ResultsTable } from './ResultsTable'

let media: MatchMediaControl

afterEach(() => media?.restore())

const rows = [
  productRow({
    product_id: 1,
    name: 'MockBook Gaming 15 MG15-4060',
    brand: 'MockBrand',
    min_price: 27_490_000,
    key_specs: { cpu_model: 'i7-13620H', gpu_model: 'RTX 4060', ram_gb: 16 },
    offers: [
      rowOffer({ site: 'gearvn', price: 27_490_000, price_type: 'member' }),
      rowOffer({
        site: 'fptshop',
        price: 28_990_000,
        price_type: 'flash',
        stock_status: 'out_of_stock',
        url: 'https://mock-fpt.example/p/1',
      }),
    ],
  }),
  productRow({
    product_id: 2,
    name: 'MockBook Air 13',
    min_price: 19_990_000,
    offers: [rowOffer()],
  }),
  productRow({
    product_id: 3,
    name: 'MockBook Pro 16',
    min_price: 35_000_000,
    offers: [rowOffer()],
  }),
]

function renderWide(list = rows) {
  media = mockMatchMedia(true)
  return renderWithProviders(<ResultsTable rows={list} />)
}

const bodyRows = () =>
  within(screen.getByRole('table', { name: 'Kết quả tìm kiếm' }))
    .getAllByRole('row')
    .slice(1)
const names = () => bodyRows().map((row) => within(row).getAllByRole('link')[0]?.textContent)

describe('ResultsTable · bảng rộng', () => {
  it('hiện tên, hãng, giá thấp nhất, thông số chính và số trang bán', () => {
    renderWide()
    const first = bodyRows()[0] as HTMLElement
    expect(
      within(first).getByRole('link', { name: 'MockBook Gaming 15 MG15-4060' }),
    ).toHaveAttribute('href', '/products/1')
    expect(within(first).getByText('MockBrand')).toBeInTheDocument()
    expect(within(first).getByText('27.490.000 ₫')).toBeInTheDocument()
    expect(within(first).getByText('RTX 4060')).toBeInTheDocument()
    expect(within(first).getByText('16 GB')).toBeInTheDocument()
    expect(within(first).getByRole('button', { name: /2 trang/ })).toBeInTheDocument()
  })

  it('rows rỗng: không dựng gì', () => {
    const { container } = renderWide([])
    expect(container).toBeEmptyDOMElement()
  })

  it('sản phẩm chưa có giá hiện "Chưa có giá"', () => {
    renderWide([productRow({ product_id: 9, min_price: null, offers: [] })])
    expect(screen.getByText('Chưa có giá')).toBeInTheDocument()
  })

  it('bấm tiêu đề cột giá: tăng → giảm → về thứ tự gốc, aria-sort đổi theo', async () => {
    renderWide()
    const header = screen.getByRole('columnheader', { name: /Giá thấp nhất/ })
    const sortButton = within(header).getByRole('button')
    expect(header).toHaveAttribute('aria-sort', 'none')

    await userEvent.click(sortButton)
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(names()).toEqual(['MockBook Air 13', 'MockBook Gaming 15 MG15-4060', 'MockBook Pro 16'])

    await userEvent.click(sortButton)
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(names()).toEqual(['MockBook Pro 16', 'MockBook Gaming 15 MG15-4060', 'MockBook Air 13'])

    await userEvent.click(sortButton)
    expect(header).toHaveAttribute('aria-sort', 'none')
    expect(names()[0]).toBe('MockBook Gaming 15 MG15-4060')
  })

  it('sắp theo tên', async () => {
    renderWide()
    await userEvent.click(screen.getByRole('button', { name: 'Sắp xếp theo Sản phẩm' }))
    expect(names()).toEqual(['MockBook Air 13', 'MockBook Gaming 15 MG15-4060', 'MockBook Pro 16'])
  })

  it('mở "Nơi bán": giá từng trang, nhãn loại giá, tình trạng hàng và liên kết an toàn', async () => {
    renderWide()
    const toggle = screen.getByRole('button', { name: /Xem giá từng trang: MockBook Gaming/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Thành viên')).toBeInTheDocument()
    expect(screen.getByText('Flash sale')).toBeInTheDocument()
    expect(screen.getByText('Hết hàng')).toBeInTheDocument()
    expect(screen.getByText('Rẻ nhất')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Mở trang FPT Shop' })
    expect(link).toHaveAttribute('href', 'https://mock-fpt.example/p/1')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')

    await userEvent.click(toggle)
    expect(screen.queryByText('Flash sale')).toBeNull()
  })

  it('liên kết offer có scheme nguy hiểm bị bỏ, không dựng thẻ a', async () => {
    renderWide([
      productRow({
        product_id: 5,
        name: 'MockBook Lạ',
        offers: [rowOffer({ url: 'javascript:alert(1)' })],
      }),
    ])
    await userEvent.click(screen.getByRole('button', { name: /Xem giá từng trang/ }))
    expect(screen.queryByRole('link', { name: /Mở trang/ })).toBeNull()
  })

  it('dữ liệu offer cũ hơn 24 giờ hiện badge vàng thay cho giờ cập nhật', async () => {
    renderWide([
      productRow({
        product_id: 6,
        name: 'MockBook Cũ',
        offers: [rowOffer({ scraped_at: '2020-01-01T00:00:00Z' })],
      }),
    ])
    await userEvent.click(screen.getByRole('button', { name: /Xem giá từng trang/ }))
    expect(screen.getByText(/Giá cập nhật lúc 07:00 01\/01/)).toBeInTheDocument()
  })
})

describe('ResultsTable · ảnh sản phẩm', () => {
  it('có ảnh http(s): dựng img không tham chiếu; ảnh lỗi thì thay bằng ô giữ chỗ', () => {
    const { container } = renderWide([
      productRow({
        product_id: 7,
        name: 'Mock Có Ảnh',
        image_url: 'https://mock-images.example/a.jpg',
      }),
    ])
    const image = container.querySelector('img') as HTMLImageElement
    expect(image).toHaveAttribute('src', 'https://mock-images.example/a.jpg')
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer')
    fireEvent.error(image)
    expect(container.querySelector('img')).toBeNull()
  })

  it('URL ảnh nguy hiểm hoặc thiếu: không dựng img', () => {
    const { container } = renderWide([
      productRow({ product_id: 7, name: 'Mock A', image_url: 'javascript:alert(1)' }),
      productRow({ product_id: 8, name: 'Mock B', image_url: null }),
    ])
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('ResultsTable · chọn để so sánh', () => {
  const box = (name: string) => screen.getByRole('checkbox', { name: `Chọn ${name} để so sánh` })

  it('nút So sánh tắt khi chọn dưới 2, bật khi đủ 2; đếm số đã chọn', async () => {
    renderWide()
    const compare = screen.getByRole('button', { name: 'So sánh' })
    expect(compare).toBeDisabled()
    expect(screen.getByText('Đã chọn 0')).toBeInTheDocument()
    expect(screen.getByText('Chọn 2–5 sản phẩm để so sánh.')).toBeInTheDocument()

    await userEvent.click(box('MockBook Air 13'))
    expect(compare).toBeDisabled()
    await userEvent.click(box('MockBook Pro 16'))
    expect(compare).toBeEnabled()
    expect(screen.getByText('Đã chọn 2')).toBeInTheDocument()

    await userEvent.click(box('MockBook Pro 16'))
    expect(compare).toBeDisabled()
  })

  it('tối đa 5 sản phẩm: các ô còn lại bị tắt và có ghi chú', async () => {
    const many = Array.from({ length: 7 }, (_, index) =>
      productRow({
        product_id: 100 + index,
        name: `Mock máy ${index + 1}`,
        min_price: 1_000_000 + index,
      }),
    )
    renderWide(many)
    for (let index = 1; index <= 5; index += 1) {
      await userEvent.click(box(`Mock máy ${index}`))
    }
    expect(screen.getByText('Tối đa 5 sản phẩm.')).toBeInTheDocument()
    expect(box('Mock máy 6')).toBeDisabled()
    expect(box('Mock máy 7')).toBeDisabled()
    expect(box('Mock máy 1')).toBeEnabled()

    await userEvent.click(box('Mock máy 1'))
    expect(box('Mock máy 6')).toBeEnabled()
  })

  it('bấm So sánh mở ngăn so sánh và gọi POST /compare đúng các id đã chọn', async () => {
    let body: unknown
    server.use(
      http.post(apiUrl('compare'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ products: [], differing_fields: [], cheapest_product_id: null })
      }),
    )
    renderWide()
    await userEvent.click(box('MockBook Pro 16'))
    await userEvent.click(box('MockBook Air 13'))
    await userEvent.click(screen.getByRole('button', { name: 'So sánh' }))

    expect(await screen.findByRole('dialog', { name: 'So sánh (2)' })).toBeInTheDocument()
    // Thứ tự theo bảng đang hiển thị, không theo thứ tự bấm chọn.
    expect(body).toEqual({ product_ids: [2, 3] })
  })
})

describe('ResultsTable · menu thao tác', () => {
  async function openMenu(name: string) {
    await userEvent.click(screen.getByRole('button', { name: `Thao tác với ${name}` }))
  }

  it('có ba mục: Xem chi tiết, Thêm vào danh sách, Báo khi giảm giá', async () => {
    renderWide()
    await openMenu('MockBook Air 13')
    expect(screen.getByRole('menuitem', { name: 'Xem chi tiết' })).toHaveAttribute(
      'href',
      '/products/2',
    )
    expect(screen.getByRole('menuitem', { name: 'Thêm vào danh sách' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Báo khi giảm giá' })).toBeInTheDocument()
  })

  it('Thêm vào danh sách mở hộp thoại cho đúng sản phẩm', async () => {
    server.use(http.get(apiUrl('lists'), () => HttpResponse.json({ items: [listSummary()] })))
    renderWide()
    await openMenu('MockBook Air 13')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Thêm vào danh sách' }))
    const dialog = await screen.findByRole('dialog', { name: 'Thêm vào danh sách mua' })
    expect(dialog).toHaveTextContent('MockBook Air 13')
  })

  it('Báo khi giảm giá mở hộp thoại kèm giá hiện tại của sản phẩm', async () => {
    renderWide()
    await openMenu('MockBook Air 13')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Báo khi giảm giá' }))
    const dialog = await screen.findByRole('dialog', { name: 'Báo khi giảm giá' })
    expect(dialog).toHaveTextContent('Giá thấp nhất hiện tại: 19.990.000 ₫')
  })
})

describe('ResultsTable · điện thoại (< 640 px)', () => {
  function renderNarrow() {
    media = mockMatchMedia(false)
    return renderWithProviders(<ResultsTable rows={rows} />)
  }

  it('chuyển thành danh sách thẻ, không có bảng', () => {
    renderNarrow()
    expect(screen.queryByRole('table')).toBeNull()
    const list = screen.getByRole('list', { name: 'Kết quả tìm kiếm' })
    expect(list.querySelectorAll(':scope > li')).toHaveLength(3)
    expect(within(list).getByText('27.490.000 ₫')).toBeInTheDocument()
  })

  it('thẻ vẫn chọn được, mở giá từng trang và có menu thao tác', async () => {
    renderNarrow()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Chọn MockBook Air 13 để so sánh' }))
    expect(screen.getByText('Đã chọn 1')).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole('button', { name: /Xem giá từng trang: MockBook Gaming/ }),
    )
    expect(screen.getByText('Thành viên')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thao tác với MockBook Pro 16' })).toBeInTheDocument()
  })

  it('đổi kích thước màn hình thì đổi giữa bảng và thẻ', async () => {
    media = mockMatchMedia(false)
    renderWithProviders(<ResultsTable rows={rows} />)
    expect(screen.queryByRole('table')).toBeNull()
    const { act } = await import('@testing-library/react')
    act(() => media.set(true))
    expect(screen.getByRole('table', { name: 'Kết quả tìm kiếm' })).toBeInTheDocument()
  })
})
