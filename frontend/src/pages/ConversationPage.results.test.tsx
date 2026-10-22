import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router'
import { apiUrl } from '@/api/client'
import { offerView, productFull, productRow, rowOffer } from '@/mocks/data'
import { server } from '@/mocks/server'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { sample, sseFrame, sseResponse } from '@/test/sse'
import { ConversationPage } from './ConversationPage'

const RUN = 'run-1'
let media: MatchMediaControl

beforeEach(() => {
  media = mockMatchMedia(true)
})
afterEach(() => media.restore())

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/c/:conversationId" element={<ConversationPage />} />
    </Routes>,
    { route },
  )
}

const message = (
  id: number,
  role: 'user' | 'assistant',
  content: string,
  payload: unknown = null,
) => ({
  message_id: id,
  role,
  content,
  payload,
  created_at: '2026-10-16T02:00:00Z',
})

describe('ConversationPage · bảng kết quả trong hội thoại', () => {
  it('câu trả lời mới có bảng từ sự kiện final: hiện sản phẩm, giá, nơi bán', async () => {
    server.use(
      http.get(apiUrl('conversations/7/messages'), () =>
        HttpResponse.json({ items: [message(1, 'user', 'laptop gaming')] }),
      ),
      http.get(apiUrl(`chat/${RUN}/events`), () =>
        sseResponse([
          sseFrame('plan', sample.plan, 0),
          sseFrame(
            'final',
            {
              ...sample.final,
              table: [
                productRow({
                  product_id: 12,
                  name: 'MockBook Gaming 15 MG15-4060',
                  offers: [
                    rowOffer({ site: 'gearvn' }),
                    rowOffer({ site: 'fptshop', price: 28_990_000 }),
                  ],
                }),
              ],
              live_items: [
                {
                  site: 'gearvn',
                  title: 'Loa Mock tìm trực tiếp',
                  price: 900_000,
                  url: 'https://mock-gearvn.example/loa',
                  scraped_at: null,
                },
              ],
            },
            1,
          ),
        ]),
      ),
    )
    renderAt(`/c/7?run=${RUN}`)

    const table = await screen.findByRole('table', { name: 'Kết quả tìm kiếm' })
    expect(within(table).getByText('MockBook Gaming 15 MG15-4060')).toBeInTheDocument()
    expect(within(table).getByText('27.490.000 ₫')).toBeInTheDocument()
    expect(within(table).getByRole('button', { name: /2 trang/ })).toBeInTheDocument()
    expect(screen.getByText('Loa Mock tìm trực tiếp')).toBeInTheDocument()
    expect(screen.getAllByText('Tìm trực tiếp – chưa chuẩn hóa thông số').length).toBeGreaterThan(0)
  })

  it('tin nhắn trợ lý cũ có payload.product_ids: tải sản phẩm và dựng bảng với giá hiện tại', async () => {
    server.use(
      http.get(apiUrl('conversations/7/messages'), () =>
        HttpResponse.json({
          items: [
            message(1, 'user', 'laptop gaming'),
            message(2, 'assistant', 'Có 2 laptop phù hợp.', { product_ids: [12, 13] }),
          ],
        }),
      ),
      http.get(apiUrl('products/:id'), ({ params }) =>
        HttpResponse.json(
          productFull({
            product_id: Number(params.id),
            name: `Mock máy ${String(params.id)}`,
            min_price: 20_000_000 + Number(params.id),
            offers: [offerView({ effective_price: 20_000_000 + Number(params.id) })],
          }),
        ),
      ),
    )
    renderAt('/c/7')
    expect(await screen.findByText('Có 2 laptop phù hợp.')).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Kết quả tìm kiếm' })
    expect(within(table).getByText('Mock máy 12')).toBeInTheDocument()
    expect(within(table).getByText('20.000.013 ₫')).toBeInTheDocument()
  })

  it('chọn hai sản phẩm trong hội thoại rồi bấm So sánh mở ngăn so sánh', async () => {
    server.use(
      http.get(apiUrl('conversations/7/messages'), () =>
        HttpResponse.json({ items: [message(1, 'user', 'laptop')] }),
      ),
      http.get(apiUrl(`chat/${RUN}/events`), () =>
        sseResponse([
          sseFrame(
            'final',
            {
              ...sample.final,
              table: [
                productRow({ product_id: 1, name: 'Mock Một' }),
                productRow({ product_id: 2, name: 'Mock Hai' }),
              ],
            },
            0,
          ),
        ]),
      ),
      http.post(apiUrl('compare'), () =>
        HttpResponse.json({
          products: [
            productFull({ product_id: 1, name: 'Mock Một' }),
            productFull({ product_id: 2, name: 'Mock Hai' }),
          ],
          differing_fields: [],
          cheapest_product_id: 1,
        }),
      ),
    )
    renderAt(`/c/7?run=${RUN}`)
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Chọn Mock Một để so sánh' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Chọn Mock Hai để so sánh' }))
    await userEvent.click(screen.getByRole('button', { name: 'So sánh' }))
    expect(await screen.findByRole('dialog', { name: 'So sánh (2)' })).toBeInTheDocument()
  })
})
