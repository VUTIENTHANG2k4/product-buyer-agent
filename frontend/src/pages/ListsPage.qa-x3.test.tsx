import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { apiUrl } from '@/api/client'
import { listDetail } from '@/mocks/data'
import { installFakeLists } from '@/test/fakeLists'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ListsPage } from './ListsPage'

const SLOW = { timeout: 5000 }
let media: MatchMediaControl

beforeEach(() => {
  media = mockMatchMedia(true)
})
afterEach(() => {
  media.restore()
  Reflect.deleteProperty(navigator, 'clipboard')
})

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/lists" element={<ListsPage />} />
      <Route path="/lists/:id" element={<ListsPage />} />
    </Routes>,
    { route },
  )
}

describe('ListsPage · xuất CSV / chia sẻ link (QA X3)', () => {
  it('chuyển sang danh sách khác: "Tải CSV" và link chép đổi theo danh sách mới', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    installFakeLists([
      listDetail({ list_id: 11, name: 'Mock A', items: [] }),
      listDetail({ list_id: 12, name: 'Mock B', items: [] }),
    ])
    renderAt('/lists/11')
    // Chờ tải dữ liệu: timeout mặc định 1 s quá sát khi cả bộ test chạy song song.
    expect(await screen.findByRole('link', { name: 'Tải CSV' }, SLOW)).toHaveAttribute(
      'href',
      apiUrl('lists/11/export.csv'),
    )

    const nav = screen.getByRole('navigation', { name: 'Danh sách của bạn' })
    await userEvent.click(within(nav).getByRole('link', { name: /Mock B/ }))
    await screen.findByRole('heading', { level: 2, name: 'Mock B' }, SLOW)

    // Tiêu đề lấy từ thanh bên nên hiện trước chi tiết danh sách 12: chờ link đổi theo nó.
    await waitFor(
      () =>
        expect(screen.getByRole('link', { name: 'Tải CSV' })).toHaveAttribute(
          'href',
          apiUrl('lists/12/export.csv'),
        ),
      SLOW,
    )
    expect(screen.getByRole('link', { name: 'Tải CSV' })).toHaveAttribute(
      'download',
      'danh-sach-12.csv',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Sao chép link' }))
    expect(writeText).toHaveBeenLastCalledWith(`${window.location.origin}/lists/12`)
  })

  it('màn hình hẹp: vẫn có "Tải CSV" và "Sao chép link"', async () => {
    media.set(false)
    installFakeLists([listDetail({ list_id: 3, name: 'Mock hẹp', items: [] })])
    renderAt('/lists/3')
    expect(await screen.findByRole('link', { name: 'Tải CSV' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sao chép link' })).toBeInTheDocument()
  })

  it('danh sách không tồn tại: không hiện nút xuất/chia sẻ', async () => {
    installFakeLists([listDetail({ list_id: 1, name: 'Mock A', items: [] })])
    renderAt('/lists/999')
    await screen.findByRole('navigation', { name: 'Danh sách của bạn' })
    expect(await screen.findByText(/không tìm thấy|không còn|đã bị xóa/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Tải CSV' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sao chép link' })).not.toBeInTheDocument()
  })
})
