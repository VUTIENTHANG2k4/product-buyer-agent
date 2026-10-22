import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { offerView, productFull } from '@/mocks/data'
import { server } from '@/mocks/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { CompareDrawer } from './CompareDrawer'

const a = productFull({
  product_id: 1,
  name: 'MockBook A',
  brand: 'MockBrand',
  min_price: 27_490_000,
  specs: {
    cpu_model: 'i7-13620H',
    gpu_model: 'RTX 4060',
    gpu_rank: 40,
    ram_gb: 16,
    refresh_hz: 144,
  },
  offers: [offerView()],
})
const b = productFull({
  product_id: 2,
  name: 'MockBook B',
  brand: 'MockBrand',
  min_price: 28_990_000,
  specs: {
    cpu_model: 'Ryzen 7 7435HS',
    gpu_model: 'RTX 4060',
    gpu_rank: 40,
    ram_gb: 16,
    refresh_hz: 165,
  },
  offers: [offerView()],
})

function comparison(over: Record<string, unknown> = {}) {
  server.use(
    http.post(apiUrl('compare'), () =>
      HttpResponse.json({
        products: [a, b],
        differing_fields: ['cpu_model', 'refresh_hz'],
        cheapest_product_id: 1,
        ...over,
      }),
    ),
  )
}

const rowOf = (label: string) =>
  screen.getByRole('rowheader', { name: new RegExp(label) }).closest('tr') as HTMLElement

describe('CompareDrawer', () => {
  it('đóng (ids = null): không dựng gì và không gọi API', () => {
    renderWithProviders(<CompareDrawer ids={null} onClose={vi.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('đang tải: hiện skeleton trong ngăn', async () => {
    comparison()
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    expect(await screen.findByRole('dialog', { name: 'So sánh (2)' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    expect(await screen.findByText('MockBook A')).toBeInTheDocument()
  })

  it('mặc định chỉ hiện khác biệt; giá luôn hiện và đánh dấu sản phẩm rẻ nhất', async () => {
    comparison()
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    await screen.findByText('MockBook A')

    expect(screen.getByRole('checkbox', { name: 'Chỉ hiện khác biệt' })).toBeChecked()
    const price = rowOf('Giá thấp nhất')
    expect(within(price).getByText('27.490.000 ₫')).toBeInTheDocument()
    expect(within(price).getByText('Rẻ nhất')).toBeInTheDocument()
    expect(within(price).getAllByText('Rẻ nhất')).toHaveLength(1)
    expect(within(rowOf('CPU')).getByText('Ryzen 7 7435HS')).toBeInTheDocument()
    expect(within(rowOf('Tần số quét')).getByText('165 Hz')).toBeInTheDocument()
    // Trường giống nhau và trường suy ra (hạng GPU) bị ẩn.
    expect(screen.queryByRole('rowheader', { name: /^RAM/ })).toBeNull()
    expect(screen.queryByRole('rowheader', { name: /GPU/ })).toBeNull()
  })

  it('bỏ chọn "Chỉ hiện khác biệt": hiện mọi trường, trường khác biệt có nhãn chữ', async () => {
    comparison()
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    await screen.findByText('MockBook A')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Chỉ hiện khác biệt' }))

    expect(within(rowOf('RAM')).getAllByText('16 GB')).toHaveLength(2)
    expect(within(rowOf('^GPU')).getAllByText('RTX 4060')).toHaveLength(2)
    expect(screen.queryByRole('rowheader', { name: /Hạng GPU/ })).toBeNull()
    expect(within(rowOf('CPU')).getByText('Khác biệt')).toBeInTheDocument()
    expect(within(rowOf('RAM')).queryByText('Khác biệt')).toBeNull()
  })

  it('không có khác biệt: giải thích thay vì bảng trống', async () => {
    comparison({ differing_fields: [] })
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    expect(await screen.findByText(/giống nhau về mọi thông số/)).toBeInTheDocument()
  })

  it('trường chỉ một máy có: máy kia hiện dấu gạch', async () => {
    const withPanel = { ...a, specs: { ...a.specs, panel: 'IPS' } }
    comparison({
      products: [withPanel, b],
      differing_fields: ['panel'],
    })
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    await screen.findByText('MockBook A')
    const row = rowOf('Tấm nền')
    expect(within(row).getByText('IPS')).toBeInTheDocument()
    expect(within(row).getByText('—')).toBeInTheDocument()
  })

  it('sản phẩm chưa có giá hiện dấu gạch và không ai được đánh dấu rẻ nhất', async () => {
    comparison({
      products: [
        { ...a, min_price: null },
        { ...b, min_price: null },
      ],
      cheapest_product_id: null,
    })
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    await screen.findByText('MockBook A')
    const price = rowOf('Giá thấp nhất')
    expect(within(price).getAllByText('—')).toHaveLength(2)
    expect(within(price).queryByText('Rẻ nhất')).toBeNull()
  })

  it('tên sản phẩm là liên kết tới trang chi tiết', async () => {
    comparison()
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    expect(await screen.findByRole('link', { name: 'MockBook B' })).toHaveAttribute(
      'href',
      '/products/2',
    )
  })

  it('id không tồn tại (404 PRODUCT_NOT_FOUND): hiện thông điệp của API và nút Thử lại', async () => {
    server.use(
      http.post(apiUrl('compare'), () =>
        HttpResponse.json(
          {
            error: {
              code: 'PRODUCT_NOT_FOUND',
              message: 'Không tìm thấy sản phẩm 2',
              details: { product_ids: [2] },
            },
          },
          { status: 404 },
        ),
      ),
    )
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={vi.fn()} />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Không tìm thấy sản phẩm 2')
    expect(within(alert).getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
  })

  it('nút đóng gọi onClose', async () => {
    comparison()
    const onClose = vi.fn()
    renderWithProviders(<CompareDrawer ids={[1, 2]} onClose={onClose} />)
    await screen.findByText('MockBook A')
    await userEvent.click(screen.getByRole('button', { name: 'Đóng' }))
    expect(onClose).toHaveBeenCalled()
  })
})
