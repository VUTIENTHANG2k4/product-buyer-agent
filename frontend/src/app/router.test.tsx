import { QueryClient } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
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

  it('đọc tham số của /products/:id', () => {
    renderAt('/products/42')
    expect(screen.getByRole('heading', { name: 'Chi tiết sản phẩm' })).toBeInTheDocument()
    expect(screen.getByText(/mã: 42/)).toBeInTheDocument()
  })

  it.each([
    ['/c/abc', 'Hội thoại', /mã: abc/],
    ['/lists', 'Danh sách mua', /^Sẽ làm ở T8\.5\.$/],
    ['/lists/7', 'Danh sách mua', /mã: 7/],
    ['/alerts', 'Cảnh báo giá', /T8\.6/],
    ['/admin', 'Quản trị', /T8\.7/],
  ])('có route %s', (path, heading, description) => {
    renderAt(path)
    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
    expect(screen.getByText(description)).toBeInTheDocument()
  })

  it('đường dẫn lạ hiện trang không tìm thấy và có đường về trang chính', async () => {
    const router = renderAt('/khong-ton-tai')
    expect(screen.getByRole('heading', { name: 'Không tìm thấy trang' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: 'Về trang chính' }))
    expect(router.state.location.pathname).toBe('/')
  })
})
