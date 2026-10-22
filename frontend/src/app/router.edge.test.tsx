import { QueryClient } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, type RouteObject } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { RouteErrorPage } from '@/pages/RouteErrorPage'
import { Providers } from './providers'
import { routes } from './router'

function renderRoutes(tree: RouteObject[], path: string) {
  const router = createMemoryRouter(tree, { initialEntries: [path] })
  const view = render(
    <Providers client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return { router, ...view }
}

const renderAt = (path: string) => renderRoutes(routes, path)

/** Layout thật (AppLayout + RouteErrorPage) với một route con do test cung cấp. */
function routesWith(child: RouteObject): RouteObject[] {
  return [{ element: <AppLayout />, errorElement: <RouteErrorPage />, children: [child] }]
}

function routesWithCrash(crash: () => never): RouteObject[] {
  return routesWith({ path: 'crash', element: <Crash run={crash} /> })
}

function Crash({ run }: { run: () => never }): never {
  return run()
}

function currentLinks(): string[] {
  return screen
    .getAllByRole('link')
    .filter((link) => link.getAttribute('aria-current') === 'page')
    .map((link) => link.textContent ?? '')
}

describe('router · tham số route lạ', () => {
  it.each([
    '/products/%3Cscript%3Ealert(1)%3C%2Fscript%3E',
    '/products/%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E',
    '/products/..%2F..%2Fadmin',
    '/products/a%20b%26c%3Dd%3F%23e',
    '/products/' + encodeURIComponent('Đà Nẵng ₫ 🙂'),
    '/products/' + encodeURIComponent('Lenovo Legion Ấ'.normalize('NFD')),
    '/products/0',
    '/products/2147483648',
  ])('%s: mã không hợp lệ → thông báo cố định, không chèn phần tử, không đổi tiêu đề', (path) => {
    const { container } = renderAt(path)
    expect(screen.getByText('Mã sản phẩm không hợp lệ.')).toBeInTheDocument()
    expect(container.querySelector('script, img')).toBeNull()
    expect(document.title).toBe('Chi tiết sản phẩm · Buyer Agent')
  })

  it('/lists/%20 (mã toàn khoảng trắng) vẫn hiện trang danh sách chi tiết, không sập', () => {
    renderAt('/lists/%20')
    expect(screen.getByRole('heading', { name: 'Danh sách mua' })).toBeInTheDocument()
    expect(document.title).toBe('Danh sách mua · Buyer Agent')
  })

  it('đường dẫn rất dài (5000 ký tự) vẫn render và không làm đổi tiêu đề', () => {
    const id = 'a'.repeat(5000)
    renderAt(`/lists/${id}`)
    expect(screen.getByText(`Sẽ làm ở T8.5. (mã: ${id})`)).toBeInTheDocument()
    expect(document.title).toBe('Danh sách mua · Buyer Agent')
  })

  it.each([
    ['/products/'],
    ['/products'],
    ['/products/1/2'],
    ['/c'],
    ['/lists/7/extra'],
    ['/alerts/x'],
    ['/admin/anything'],
    ['/%E0%A4%A'],
  ])('%s hiện trang không tìm thấy với đường về trang chính', (path) => {
    renderAt(path)
    expect(screen.getByRole('heading', { name: 'Không tìm thấy trang' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Về trang chính' })).toHaveAttribute('href', '/')
    expect(document.title).toBe('Không tìm thấy trang · Buyer Agent')
  })

  it.each(['/products/%E0%A4%A', '/c/%ZZ', '/lists/%'])(
    'mã có chuỗi %% sai định dạng (%s) không làm sập ứng dụng',
    (path) => {
      renderAt(path)
      expect(screen.getByRole('main')).toBeInTheDocument()
      expect(screen.queryByText('Trang gặp lỗi')).not.toBeInTheDocument()
    },
  )

  it('mỗi màn hình có đúng một <main> và đúng một <h1>', () => {
    for (const path of [
      '/',
      '/c/1',
      '/products/1',
      '/lists',
      '/lists/1',
      '/alerts',
      '/admin',
      '/x',
    ]) {
      const { unmount } = renderAt(path)
      expect(screen.getAllByRole('main')).toHaveLength(1)
      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
      unmount()
    }
  })

  it('đường dẫn không phân biệt hoa thường tới đúng trang và vẫn có tiêu đề đúng', () => {
    renderAt('/Lists')
    expect(screen.getByRole('heading', { name: 'Danh sách mua' })).toBeInTheDocument()
    expect(document.title).toBe('Danh sách mua · Buyer Agent')
  })
})

describe('router · điều hướng và document.title', () => {
  it('điều hướng liên tiếp qua nhiều route luôn đặt tiêu đề của route cuối', async () => {
    renderAt('/')
    for (const [link, title] of [
      ['Danh sách mua', 'Danh sách mua · Buyer Agent'],
      ['Cảnh báo', 'Cảnh báo giá · Buyer Agent'],
      ['Quản trị', 'Quản trị · Buyer Agent'],
      ['Hỏi agent', 'Hỏi agent · Buyer Agent'],
    ] as const) {
      await userEvent.click(screen.getByRole('link', { name: link }))
      expect(document.title).toBe(title)
    }
  })

  it('đi từ route có tiêu đề sang trang không tìm thấy rồi quay lại bằng "Về trang chính"', async () => {
    const { router } = renderAt('/lists/7')
    await act(() => router.navigate('/khong-ton-tai'))
    expect(document.title).toBe('Không tìm thấy trang · Buyer Agent')
    await userEvent.click(screen.getByRole('link', { name: 'Về trang chính' }))
    expect(document.title).toBe('Hỏi agent · Buyer Agent')
  })
})

describe('NavBar · aria-current', () => {
  it('/lists/7 làm nổi mục "Danh sách mua" và không mục nào khác', () => {
    renderAt('/lists/7')
    expect(currentLinks()).toEqual(['Danh sách mua'])
  })

  it('/lists/ (có dấu / cuối) vẫn làm nổi mục "Danh sách mua"', () => {
    renderAt('/lists/')
    expect(currentLinks()).toEqual(['Danh sách mua'])
  })

  it('/listsfoo (trùng tiền tố nhưng khác đoạn) không làm nổi mục nào', () => {
    renderAt('/listsfoo')
    expect(currentLinks()).toEqual([])
  })

  it.each(['/products/42', '/khong-ton-tai'])(
    '%s không làm nổi mục nào của thanh điều hướng',
    (path) => {
      renderAt(path)
      expect(currentLinks()).toEqual([])
    },
  )

  it('"Hỏi agent" chỉ nổi ở "/", không nổi ở /lists dù "/" là tiền tố của mọi đường dẫn', () => {
    renderAt('/lists')
    expect(screen.getByRole('link', { name: 'Hỏi agent' })).not.toHaveAttribute('aria-current')
  })

  it('mỗi lần chỉ có tối đa một mục được đánh dấu aria-current', async () => {
    renderAt('/')
    for (const name of ['Danh sách mua', 'Cảnh báo', 'Quản trị', 'Hỏi agent']) {
      await userEvent.click(screen.getByRole('link', { name }))
      expect(currentLinks()).toEqual([name])
    }
  })

  // Hội thoại thuộc luồng "Hỏi agent" (docs/08 §2); trang chi tiết sản phẩm là trang con, không nổi mục nào.
  it.each(['/c/7', '/c/7/'])('%s làm nổi "Hỏi agent" và không mục nào khác', (path) => {
    renderAt(path)
    expect(currentLinks()).toEqual(['Hỏi agent'])
  })

  it('/c/7/khac là trang không tìm thấy nên "Hỏi agent" không nổi', () => {
    renderAt('/c/7/khac')
    expect(screen.getByRole('heading', { name: 'Không tìm thấy trang' })).toBeInTheDocument()
    expect(currentLinks()).toEqual([])
  })

  it.each(['/alerts/x', '/admin/anything'])(
    '%s là trang không tìm thấy nên không mục nào được đánh dấu là trang hiện tại',
    (path) => {
      renderAt(path)
      expect(screen.getByRole('heading', { name: 'Không tìm thấy trang' })).toBeInTheDocument()
      expect(currentLinks()).toEqual([])
    },
  )
})

describe('liên kết "Bỏ qua tới nội dung"', () => {
  it('là phần tử có thể focus đầu tiên của tài liệu', () => {
    renderAt('/lists')
    const first = screen
      .getAllByRole('link')
      .concat(screen.queryAllByRole('button'))
      .find((el) => el.tabIndex >= 0)
    expect(first).toBe(screen.getByRole('link', { name: 'Bỏ qua tới nội dung' }))
  })

  it('Tab từ liên kết bỏ qua đi tiếp tới mục đầu tiên của thanh điều hướng', async () => {
    renderAt('/')
    await userEvent.tab()
    expect(screen.getByRole('link', { name: 'Bỏ qua tới nội dung' })).toHaveFocus()
    await userEvent.tab()
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' })
    expect(within(nav).getByRole('link', { name: 'Hỏi agent' })).toHaveFocus()
  })

  it('Shift+Tab từ liên kết bỏ qua đưa focus ra khỏi nội dung, không kẹt trong <main>', async () => {
    renderAt('/')
    await userEvent.tab()
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('main')).not.toHaveFocus()
    expect(screen.getByRole('link', { name: 'Bỏ qua tới nội dung' })).not.toHaveFocus()
  })

  it('bấm liên tiếp nhiều lần luôn đưa focus vào <main> và không thêm mục vào lịch sử hay đổi URL', async () => {
    const { router } = renderAt('/alerts')
    const before = router.state.location
    const skip = screen.getByRole('link', { name: 'Bỏ qua tới nội dung' })
    for (let i = 0; i < 3; i += 1) {
      await userEvent.click(skip)
      expect(screen.getByRole('main')).toHaveFocus()
      await userEvent.tab({ shift: true }) // rời <main> để lần bấm sau tạo thay đổi focus thật
    }
    expect(router.state.location).toBe(before)
    expect(router.state.historyAction).toBe('POP')
    expect(window.location.hash).toBe('')
  })

  it('kích hoạt bằng phím Space/Enter không làm mất liên kết khỏi cây truy cập', async () => {
    renderAt('/')
    await userEvent.tab()
    await userEvent.keyboard('{Enter}')
    expect(screen.getByRole('link', { name: 'Bỏ qua tới nội dung' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Bỏ qua tới nội dung' })).toHaveAttribute(
      'href',
      '#main-content',
    )
  })

  it('<main> chỉ focus được bằng mã (tabindex=-1), không chen vào thứ tự Tab', async () => {
    renderAt('/')
    expect(screen.getByRole('main')).toHaveAttribute('tabindex', '-1')
    for (let i = 0; i < 8; i += 1) {
      await userEvent.tab()
      expect(screen.getByRole('main')).not.toHaveFocus()
    }
  })
})

describe('RouteErrorPage trong cây route thật', () => {
  function silenceReactErrors() {
    vi.spyOn(console, 'error').mockImplementation(() => {})
  }

  it.each([
    [
      'Error có stack',
      () => {
        throw new Error('SELECT * FROM users; at /srv/app/secret.py:12')
      },
    ],
    [
      'chuỗi',
      () => {
        throw 'mật khẩu: hunter2'
      },
    ],
    [
      'đối tượng',
      () => {
        throw { token: 'abc123', stack: 'trace' }
      },
    ],
    [
      'null',
      () => {
        throw null
      },
    ],
    [
      'HTML trong thông điệp',
      () => {
        throw new Error('<img src=x onerror=alert(1)>')
      },
    ],
    [
      'Response 500',
      () => {
        throw new Response('lỗi nội bộ bí mật', { status: 500, statusText: 'Bí mật' })
      },
    ],
  ] as [string, () => never][])(
    'khi trang con ném %s: chỉ hiện thông điệp chung tiếng Việt',
    (_n, crash) => {
      silenceReactErrors()
      const { container } = renderRoutes(routesWithCrash(crash), '/crash')

      expect(screen.getByRole('heading', { name: 'Trang gặp lỗi' })).toBeInTheDocument()
      expect(screen.getByText('Đã có lỗi xảy ra. Hãy thử lại.')).toBeInTheDocument()
      const text = container.textContent ?? ''
      for (const secret of [
        'SELECT',
        'secret.py',
        'hunter2',
        'abc123',
        'trace',
        'Bí mật',
        'bí mật',
      ]) {
        expect(text).not.toContain(secret)
      }
      expect(container.querySelector('img')).toBeNull()
    },
  )

  it('lỗi ném từ loader cũng hiện trang lỗi chung và không lộ thông điệp', () => {
    silenceReactErrors()
    const loader = (): never => {
      throw new Error('chi tiết nội bộ của loader')
    }
    // loader chạy bất đồng bộ nên dùng route con thật nhưng không có element ném lỗi
    renderRoutes(routesWith({ path: 'crash', element: <p>không tới đây</p>, loader }), '/crash')
    return screen.findByRole('heading', { name: 'Trang gặp lỗi' }).then(() => {
      expect(screen.queryByText(/chi tiết nội bộ/)).not.toBeInTheDocument()
    })
  })

  it('trang lỗi thay thế cả layout: đúng một <main> có id và đúng một liên kết về trang chính', () => {
    silenceReactErrors()
    renderRoutes(
      routesWithCrash(() => {
        throw new Error('x')
      }),
      '/crash',
    )
    expect(screen.getAllByRole('main')).toHaveLength(1)
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content')
    expect(screen.getAllByRole('link', { name: 'Về trang chính' })).toHaveLength(1)
    expect(document.title).toBe('Trang gặp lỗi · Buyer Agent')
  })
})
