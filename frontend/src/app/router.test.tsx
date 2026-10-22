import { QueryClient } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { apiUrl } from '@/api/client'
import { productFull } from '@/mocks/data'
import { server } from '@/mocks/server'
import { Providers } from './providers'
import { routes } from './router'

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <Providers client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return router
}

describe('router', () => {
  it('hiển thị layout với thanh điều hướng và trang chính', () => {
    renderAt('/')
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' })
    const linkNames = within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent)
    expect(linkNames).toEqual(['Hỏi agent', 'Danh sách mua', 'Cảnh báo', 'Quản trị'])
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Hỏi agent' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('heading', { name: 'Bạn muốn mua gì hôm nay?' })).toBeInTheDocument()
  })

  it('điều hướng từ / sang /lists và đổi liên kết đang chọn', async () => {
    const router = renderAt('/')
    await userEvent.click(screen.getByRole('link', { name: 'Danh sách mua' }))

    expect(router.state.location.pathname).toBe('/lists')
    expect(screen.getByRole('heading', { name: 'Danh sách mua' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Danh sách mua' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('link', { name: 'Hỏi agent' })).not.toHaveAttribute('aria-current')
  })

  it('đọc tham số của /products/:id và tải đúng sản phẩm đó', async () => {
    let requested = ''
    server.use(
      http.get(apiUrl('products/:id'), ({ params }) => {
        requested = String(params.id)
        return HttpResponse.json(productFull({ product_id: 42, name: 'MockBook Số 42' }))
      }),
    )
    renderAt('/products/42')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'MockBook Số 42' }),
    ).toBeInTheDocument()
    expect(requested).toBe('42')
  })

  it.each([
    ['/c/abc', 'Hội thoại', /Không tìm thấy hội thoại này/],
    ['/lists', 'Danh sách mua', /Bạn chưa có danh sách mua nào/],
    ['/lists/7', 'Danh sách mua', /Danh sách này chưa có sản phẩm/],
    ['/alerts', 'Cảnh báo giá', /T8\.6/],
    ['/admin', 'Quản trị', /T8\.7/],
  ])('có route %s', async (path, heading, description) => {
    renderAt(path)
    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
    expect(await screen.findByText(description)).toBeInTheDocument()
  })

  it('liên kết "Bỏ qua tới nội dung" là mục đầu tiên khi bấm Tab và chuyển focus vào <main>', async () => {
    renderAt('/lists')
    await userEvent.tab()
    const skipLink = screen.getByRole('link', { name: 'Bỏ qua tới nội dung' })
    expect(skipLink).toHaveFocus()

    await userEvent.keyboard('{Enter}')
    expect(screen.getByRole('main')).toHaveFocus()
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content')
    // Router bộ nhớ không đổi URL của jsdom; hash chỉ đổi nếu mặc định của thẻ <a> không bị chặn.
    expect(window.location.hash).toBe('')
  })

  it.each([
    ['/', 'Hỏi agent · Buyer Agent'],
    ['/c/abc', 'Hội thoại · Buyer Agent'],
    ['/products/42', 'Chi tiết sản phẩm · Buyer Agent'],
    ['/lists', 'Danh sách mua · Buyer Agent'],
    ['/lists/7', 'Danh sách mua · Buyer Agent'],
    ['/alerts', 'Cảnh báo giá · Buyer Agent'],
    ['/admin', 'Quản trị · Buyer Agent'],
    ['/khong-ton-tai', 'Không tìm thấy trang · Buyer Agent'],
  ])('đặt document.title của %s là "%s"', (path, title) => {
    renderAt(path)
    expect(document.title).toBe(title)
  })

  it('đổi document.title khi điều hướng sang route khác', async () => {
    renderAt('/')
    await userEvent.click(screen.getByRole('link', { name: 'Cảnh báo' }))
    expect(document.title).toBe('Cảnh báo giá · Buyer Agent')
  })

  it('đường dẫn lạ hiện trang không tìm thấy và có đường về trang chính', async () => {
    const router = renderAt('/khong-ton-tai')
    expect(screen.getByRole('heading', { name: 'Không tìm thấy trang' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: 'Về trang chính' }))
    expect(router.state.location.pathname).toBe('/')
  })
})
