import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { apiUrl } from '@/api/client'
import { Providers } from '@/app/providers'
import { offerView, productFull, productRow, rowOffer } from '@/mocks/data'
import { server } from '@/mocks/server'
import { ProductDetailView } from '@/features/catalog/ProductDetailView'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { createTestQueryClient, renderWithProviders } from '@/test/renderWithProviders'
import { OffersList } from './OffersList'
import { lowestInStockPrice } from './rows'
import { ResultsTable } from './ResultsTable'

let media: MatchMediaControl | undefined

/** Giữ provider qua `rerender` (renderWithProviders dựng lại cả cây nên mất provider). */
function renderTable(rows: ReturnType<typeof productRow>[]) {
  const client = createTestQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Providers client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </Providers>
  )
  return render(<ResultsTable rows={rows} />, { wrapper })
}
afterEach(() => media?.restore())

describe('lowestInStockPrice · "Rẻ nhất" chỉ tính offer còn hàng (T8.12)', () => {
  const price = (o: { price: number }) => o.price

  it('bỏ qua offer hết hàng dù rẻ hơn', () => {
    const offers = [
      { price: 20_000_000, stock_status: 'out_of_stock' },
      { price: 25_000_000, stock_status: 'in_stock' },
      { price: 24_000_000, stock_status: 'in_stock' },
    ]
    expect(lowestInStockPrice(offers, price)).toBe(24_000_000)
  })

  it('hết hàng cả hoặc rỗng → null', () => {
    expect(lowestInStockPrice([{ price: 1, stock_status: 'out_of_stock' }], price)).toBeNull()
    expect(lowestInStockPrice([], price)).toBeNull()
  })
})

describe('OffersList · nhãn "Rẻ nhất" (T8.12)', () => {
  it('offer hết hàng rẻ nhất không có nhãn; nhãn ở offer còn hàng rẻ nhất', () => {
    renderWithProviders(
      <OffersList
        offers={[
          rowOffer({ site: 'gearvn', price: 20_000_000, stock_status: 'out_of_stock' }),
          rowOffer({ site: 'fptshop', price: 25_000_000, stock_status: 'in_stock' }),
        ]}
      />,
    )
    const items = screen.getAllByRole('listitem')
    expect(within(items[0] as HTMLElement).queryByText('Rẻ nhất')).not.toBeInTheDocument()
    expect(within(items[1] as HTMLElement).getByText('Rẻ nhất')).toBeInTheDocument()
  })

  it('mọi offer hết hàng → không nhãn nào', () => {
    renderWithProviders(
      <OffersList offers={[rowOffer({ price: 20_000_000, stock_status: 'out_of_stock' })]} />,
    )
    expect(screen.queryByText('Rẻ nhất')).not.toBeInTheDocument()
  })
})

describe('ProductDetailView · bảng giá theo trang (T8.12)', () => {
  it('offer hết hàng rẻ nhất không được gắn "Rẻ nhất"', () => {
    server.use(
      http.get(apiUrl('products/12/price-history'), () =>
        HttpResponse.json({ series: [], min_price: null, max_price: null }),
      ),
    )
    const product = productFull({
      offers: [
        offerView({
          offer_id: 1,
          site: 'gearvn',
          price: 20_000_000,
          effective_price: 20_000_000,
          stock_status: 'out_of_stock',
        }),
        offerView({
          offer_id: 2,
          site: 'fptshop',
          price: 25_000_000,
          effective_price: 25_000_000,
          stock_status: 'in_stock',
        }),
      ],
    })
    renderWithProviders(<ProductDetailView product={product} />)
    const table = screen.getByRole('table', { name: 'Giá theo trang' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0] as HTMLElement).queryByText('Rẻ nhất')).not.toBeInTheDocument()
    expect(within(rows[1] as HTMLElement).getByText('Rẻ nhất')).toBeInTheDocument()
  })
})

describe('ResultsTable · id đã chọn không còn trong rows (T8.12)', () => {
  const make = (id: number) =>
    productRow({
      product_id: id,
      name: `Mock sản phẩm ${id}`,
      min_price: 1_000_000 * id,
      offers: [rowOffer()],
    })

  it('rows đổi và mất một id đã chọn → số đã chọn giảm, nút so sánh tắt lại', async () => {
    media = mockMatchMedia(true)
    const user = userEvent.setup()
    const { rerender } = renderTable([make(1), make(2), make(3)])
    await user.click(screen.getByRole('checkbox', { name: /Mock sản phẩm 1/ }))
    await user.click(screen.getByRole('checkbox', { name: /Mock sản phẩm 2/ }))
    expect(screen.getByText('Đã chọn 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'So sánh' })).toBeEnabled()

    rerender(<ResultsTable rows={[make(2), make(3)]} />)
    expect(screen.getByText('Đã chọn 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'So sánh' })).toBeDisabled()
  })

  it('id đã mất không chiếm chỗ trong giới hạn 5 sản phẩm', async () => {
    media = mockMatchMedia(true)
    const user = userEvent.setup()
    const initial = [1, 2, 3, 4, 5, 6].map(make)
    const { rerender } = renderTable(initial)
    for (const id of [1, 2, 3, 4, 5]) {
      await user.click(screen.getByRole('checkbox', { name: new RegExp(`Mock sản phẩm ${id} để`) }))
    }
    expect(screen.getByRole('checkbox', { name: /Mock sản phẩm 6/ })).toBeDisabled()

    rerender(<ResultsTable rows={[2, 3, 4, 5, 6].map(make)} />)
    expect(screen.getByText('Đã chọn 4')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Mock sản phẩm 6/ })).toBeEnabled()
  })

  it('id đã mất rồi quay lại không tự được chọn lại', async () => {
    media = mockMatchMedia(true)
    const user = userEvent.setup()
    const { rerender } = renderTable([make(1), make(2), make(3)])
    await user.click(screen.getByRole('checkbox', { name: /Mock sản phẩm 1 để/ }))
    await user.click(screen.getByRole('checkbox', { name: /Mock sản phẩm 2 để/ }))

    rerender(<ResultsTable rows={[make(2), make(3)]} />)
    // Bấm một ô khi id 1 đã mất: state bị dọn, id 1 không còn "ngủ" trong đó.
    await user.click(screen.getByRole('checkbox', { name: /Mock sản phẩm 3 để/ }))
    rerender(<ResultsTable rows={[make(1), make(2), make(3)]} />)

    expect(screen.getByRole('checkbox', { name: /Mock sản phẩm 1 để/ })).not.toBeChecked()
    expect(screen.getByText('Đã chọn 2')).toBeInTheDocument()
  })
})
