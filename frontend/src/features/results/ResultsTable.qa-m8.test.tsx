import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import type { Schemas } from '@/api/types'
import { productRow, rowOffer } from '@/mocks/data'
import { server } from '@/mocks/server'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ResultsTable } from './ResultsTable'

let media: MatchMediaControl
afterEach(() => media?.restore())

function renderRows(list: Schemas['ProductRow'][], wide = true) {
  media = mockMatchMedia(wide)
  return renderWithProviders(<ResultsTable rows={list} />)
}

const bodyRows = () =>
  within(screen.getByRole('table', { name: 'Kết quả tìm kiếm' }))
    .getAllByRole('row')
    .slice(1)

describe('ResultsTable · dữ liệu biên (QA M8)', () => {
  it('hàng thiếu key_specs, offers và ảnh: vẫn hiện tên, hãng, giá và dấu gạch ở cột nơi bán', () => {
    const sparse = productRow({
      product_id: 1,
      key_specs: {},
      offers: undefined,
      image_url: undefined,
    })
    renderRows([sparse])
    const [row] = bodyRows()
    expect(within(row!).getByRole('link', { name: sparse.name })).toHaveAttribute(
      'href',
      '/products/1',
    )
    expect(within(row!).getByText('MockBrand')).toBeInTheDocument()
    expect(within(row!).getByText('27.490.000 ₫')).toBeInTheDocument()
    expect(within(row!).queryByRole('button', { name: /trang bán/i })).toBeNull()
  })

  it.each([
    [null, 'Chưa có giá'],
    [undefined, 'Chưa có giá'],
    [0, '0 ₫'],
    [5_000_000_000, '5.000.000.000 ₫'],
  ])('min_price = %s hiện %j', (price, expected) => {
    renderRows([productRow({ min_price: price, offers: [] })])
    expect(within(bodyRows()[0]!).getByText(expected)).toBeInTheDocument()
  })

  it('tên có HTML, emoji và 3.000 ký tự hiện như văn bản; không dựng phần tử từ tên', () => {
    const name = `<img src=x onerror=alert(1)> 🎮 Đà Nẵng ${'x'.repeat(3000)}`
    const { container } = renderRows([productRow({ product_id: 7, name, offers: [] })])
    expect(container.querySelector('img[src="x"]')).toBeNull()
    expect(within(bodyRows()[0]!).getByRole('link', { name })).toHaveAttribute(
      'href',
      '/products/7',
    )
  })

  it('thông số lạ (khóa không có nhãn, giá trị boolean/mảng/0) hiện đủ, giá trị thiếu bị bỏ', () => {
    renderRows([
      productRow({
        key_specs: {
          truong_la: 'giá trị lạ',
          has_numpad: false,
          ports: ['USB-C', 'HDMI'],
          ram_gb: 0,
          empty: '',
          nothing: null,
        },
        offers: [],
      }),
    ])
    const row = within(bodyRows()[0]!)
    expect(row.getByText('truong_la:')).toBeInTheDocument()
    expect(row.getByText('giá trị lạ')).toBeInTheDocument()
    expect(row.getByText('Không')).toBeInTheDocument()
    expect(row.queryByText('empty:')).toBeNull()
    expect(row.queryByText('nothing:')).toBeNull()
  })

  it('chọn hai máy rồi sắp theo tên: so sánh gửi id theo thứ tự đang hiển thị', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post(apiUrl('compare'), async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({
          products: [],
          differing_fields: [],
          cheapest_product_id: null,
        })
      }),
    )
    renderRows([
      productRow({ product_id: 1, name: 'Zeta', offers: [] }),
      productRow({ product_id: 2, name: 'Alpha', offers: [] }),
      productRow({ product_id: 3, name: 'Mid', offers: [] }),
    ])
    await userEvent.click(screen.getByRole('checkbox', { name: /Zeta/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Alpha/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Sắp xếp theo Sản phẩm' }))
    await userEvent.click(screen.getByRole('button', { name: 'So sánh' }))
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ product_ids: [2, 1] })
  })

  it('sắp xếp không làm mất lựa chọn và không đóng phần "Nơi bán" đang mở', async () => {
    renderRows([
      productRow({ product_id: 1, name: 'B máy', min_price: 2, offers: [rowOffer()] }),
      productRow({ product_id: 2, name: 'A máy', min_price: 1, offers: [rowOffer()] }),
    ])
    await userEvent.click(screen.getByRole('checkbox', { name: /B máy/ }))
    await userEvent.click(
      screen.getByRole('button', { name: /1 trang, (Xem|Ẩn) giá từng trang: B máy/ }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Sắp xếp theo Giá thấp nhất' }))
    expect(screen.getByRole('checkbox', { name: /B máy/ })).toBeChecked()
    expect(
      screen.getByRole('button', { name: /1 trang, (Xem|Ẩn) giá từng trang: B máy/ }),
    ).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Mở trang')).toBeInTheDocument()
  })

  it('offer có giá 0 cạnh offer 27 triệu: giá 0 được gắn nhãn rẻ nhất, không bị bỏ như giá thiếu', async () => {
    renderRows([
      productRow({
        offers: [
          rowOffer({ site: 'gearvn', price: 0 }),
          rowOffer({ site: 'fptshop', price: 27_000_000 }),
        ],
      }),
    ])
    await userEvent.click(screen.getByRole('button', { name: /2 trang, Xem giá từng trang/ }))
    const items = screen.getAllByRole('listitem')
    const cheapest = items.filter((item) => within(item).queryByText('Rẻ nhất'))
    expect(cheapest).toHaveLength(1)
    expect(within(cheapest[0]!).getByText('0 ₫')).toBeInTheDocument()
  })
})
