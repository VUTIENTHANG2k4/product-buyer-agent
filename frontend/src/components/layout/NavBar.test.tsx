import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import { listSummary } from '@/mocks/data'
import { server } from '@/mocks/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { NavBar } from './NavBar'

describe('NavBar · số mục danh sách mua', () => {
  it('chưa có mục nào: không hiện số', async () => {
    renderWithProviders(<NavBar />)
    expect(await screen.findByRole('link', { name: 'Danh sách mua' })).toBeInTheDocument()
  })

  it('cộng số mục của mọi danh sách', async () => {
    server.use(
      http.get(apiUrl('lists'), () =>
        HttpResponse.json({
          items: [listSummary({ item_count: 2 }), listSummary({ list_id: 2, item_count: 3 })],
        }),
      ),
    )
    renderWithProviders(<NavBar />)
    expect(await screen.findByRole('link', { name: 'Danh sách mua (5)' })).toBeInTheDocument()
  })

  it('lỗi tải danh sách không làm mất điều hướng', async () => {
    server.use(http.get(apiUrl('lists'), () => HttpResponse.error()))
    const { client } = renderWithProviders(<NavBar />)
    await waitFor(() => expect(client.getQueryState(queryKeys.lists.all)?.status).toBe('error'))
    expect(screen.getByRole('link', { name: 'Danh sách mua' })).toBeInTheDocument()
    expect(screen.getAllByRole('link')).toHaveLength(4)
  })
})
