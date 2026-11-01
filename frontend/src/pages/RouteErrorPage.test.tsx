import { render, screen } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { RouteErrorPage } from './RouteErrorPage'

function Boom(): never {
  throw new Error('chi tiết kỹ thuật không được lộ ra')
}

describe('RouteErrorPage', () => {
  it('hiện thông điệp tiếng Việt và đường về trang chính, không lộ chi tiết lỗi', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const router = createMemoryRouter([
      { path: '/', element: <Boom />, errorElement: <RouteErrorPage /> },
    ])
    render(<RouterProvider router={router} />)

    expect(screen.getByRole('heading', { name: 'Trang gặp lỗi' })).toBeInTheDocument()
    expect(screen.getByText('Đã có lỗi xảy ra. Hãy thử lại.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Về trang chính' })).toHaveAttribute('href', '/')
    expect(screen.queryByText(/chi tiết kỹ thuật/)).not.toBeInTheDocument()
  })

  it('đặt document.title và id cho <main> khi route lỗi', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const router = createMemoryRouter([
      { path: '/', element: <Boom />, errorElement: <RouteErrorPage /> },
    ])
    render(<RouterProvider router={router} />)

    expect(document.title).toBe('Trang gặp lỗi · Buyer Agent')
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content')
  })
})
