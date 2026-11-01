import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { offerView, productFull } from '@/mocks/data'
import { server } from '@/mocks/server'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ProductIdsTable } from './ProductIdsTable'
import { productIdsOf } from './productIds'

let media: MatchMediaControl
beforeEach(() => {
  media = mockMatchMedia(true)
})
afterEach(() => media.restore())

function products(map: Record<number, ReturnType<typeof productFull> | 'error'>) {
  server.use(
    http.get(apiUrl('products/:id'), ({ params }) => {
      const found = map[Number(params.id)]
      if (found === undefined || found === 'error') {
        return HttpResponse.json(
          {
            error: {
              code: 'PRODUCT_NOT_FOUND',
              message: `Không tìm thấy sản phẩm ${String(params.id)}`,
              details: {},
            },
          },
          { status: 404 },
        )
      }
      return HttpResponse.json(found)
    }),
  )
}

describe('productIdsOf', () => {
  it('lấy các id nguyên từ payload, bỏ phần tử lạ', () => {
    expect(productIdsOf({ product_ids: [1, 2, 3] })).toEqual([1, 2, 3])
    expect(productIdsOf({ product_ids: [1, '2', null, 3.5, 4] })).toEqual([1, 4])
  })

  it.each([null, undefined, {}, { product_ids: 'x' }, { product_ids: null }, { other: [1] }])(
    'payload %j → không có id',
    (payload) => {
      expect(productIdsOf(payload as never)).toEqual([])
    },
  )
})

describe('ProductIdsTable', () => {
  it('không có id: không dựng gì', () => {
    const { container } = renderWithProviders(<ProductIdsTable ids={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('đang tải: skeleton; xong: bảng theo đúng thứ tự id với giá hiện tại', async () => {
    products({
      5: productFull({
        product_id: 5,
        name: 'Mock Năm',
        min_price: 30_000_000,
        offers: [offerView()],
      }),
      3: productFull({
        product_id: 3,
        name: 'Mock Ba',
        min_price: 20_000_000,
        offers: [offerView()],
      }),
    })
    renderWithProviders(<ProductIdsTable ids={[5, 3]} />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    await screen.findByText('Mock Năm')
    const names = screen.getAllByRole('link').map((link) => link.textContent)
    expect(names.indexOf('Mock Năm')).toBeLessThan(names.indexOf('Mock Ba'))
    expect(screen.getByText('20.000.000 ₫')).toBeInTheDocument()
  })

  it('một sản phẩm không tải được thì bỏ qua, các sản phẩm còn lại vẫn hiện', async () => {
    products({ 5: productFull({ product_id: 5, name: 'Mock Năm' }), 6: 'error' })
    renderWithProviders(<ProductIdsTable ids={[5, 6]} />)
    expect(await screen.findByText('Mock Năm')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('không tải được sản phẩm nào: hiện lỗi với nút Thử lại', async () => {
    products({ 6: 'error' })
    renderWithProviders(<ProductIdsTable ids={[6]} />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Không tìm thấy sản phẩm 6')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument())
  })
})
