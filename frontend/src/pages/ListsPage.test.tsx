import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes, useLocation } from 'react-router'
import { apiUrl } from '@/api/client'
import { listDetail, listItem, offerView, productFull } from '@/mocks/data'
import { server } from '@/mocks/server'
import { installFakeLists } from '@/test/fakeLists'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ListsPage } from './ListsPage'

let media: MatchMediaControl

beforeEach(() => {
  media = mockMatchMedia(true)
})
afterEach(() => media.restore())

function Where() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname}</p>
}

function renderAt(route: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/lists" element={<ListsPage />} />
        <Route path="/lists/:id" element={<ListsPage />} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}

const laptop = listItem({
  item_id: 1,
  name: 'MockBook Gaming 15',
  quantity: 2,
  current_price: 27_490_000,
  best_offer: offerView({ site: 'gearvn' }),
})
const mouse = listItem({
  item_id: 2,
  product_id: 20,
  name: 'Chuột Mock M1',
  quantity: 1,
  price_at_add: 500_000,
  current_price: 550_000,
  price_delta: 50_000,
  note: 'màu đen',
})
const goneItem = listItem({
  item_id: 3,
  product_id: 30,
  name: 'Tai nghe Mock H1',
  current_price: null,
  price_delta: null,
  best_offer: null,
})

const where = () => screen.getByTestId('where')

function itemCard(name: string): HTMLElement {
  const link = screen.getByRole('link', { name })
  return link.closest('li') as HTMLElement
}

describe('ListsPage · điều hướng và trạng thái', () => {
  it('đang tải: skeleton và h1 "Danh sách mua"', async () => {
    installFakeLists([listDetail({ items: [laptop] })])
    renderAt('/lists/1')
    expect(screen.getByRole('heading', { level: 1, name: 'Danh sách mua' })).toBeInTheDocument()
    expect(screen.getAllByRole('status')[0]).toHaveAttribute('aria-busy', 'true')
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Mock danh sách laptop' }),
    ).toBeInTheDocument()
  })

  it('/lists mở danh sách đầu tiên (thay thế lịch sử)', async () => {
    installFakeLists([
      listDetail({ list_id: 5, name: 'Mock đầu', items: [] }),
      listDetail({ list_id: 6, name: 'Mock hai', items: [] }),
    ])
    renderAt('/lists')
    await waitFor(() => expect(where()).toHaveTextContent('/lists/5'))
    expect(await screen.findByRole('heading', { level: 2, name: 'Mock đầu' })).toBeInTheDocument()
  })

  it('chưa có danh sách: trạng thái rỗng, vẫn tạo được danh sách', async () => {
    installFakeLists([])
    renderAt('/lists')
    expect(await screen.findByText('Bạn chưa có danh sách mua nào')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Nhờ agent tìm sản phẩm' })).toHaveAttribute(
      'href',
      '/',
    )
    expect(screen.getByLabelText('Tên danh sách mới')).toBeInTheDocument()
  })

  it('lỗi tải danh sách: thông điệp tiếng Việt và "Thử lại" thành công', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('lists'), () => {
        calls += 1
        return calls <= 1 ? HttpResponse.error() : HttpResponse.json({ items: [] })
      }),
    )
    renderAt('/lists')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Không tải được danh sách')
    await userEvent.click(within(alert).getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('Bạn chưa có danh sách mua nào')).toBeInTheDocument()
  })

  it.each(['abc', '0', '-2', '2147483648', '1.5'])('mã %s không hợp lệ: báo ngay', async (id) => {
    installFakeLists([listDetail()])
    renderAt(`/lists/${id}`)
    expect(await screen.findByText('Mã danh sách không hợp lệ.')).toBeInTheDocument()
  })

  it('danh sách không tồn tại (404 LIST_NOT_FOUND): hiện thông điệp của API', async () => {
    installFakeLists([listDetail({ list_id: 1 })])
    renderAt('/lists/99')
    expect(await screen.findByText('Không tìm thấy danh sách')).toBeInTheDocument()
  })

  it('cột bên trái liệt kê danh sách kèm số mục, danh sách đang mở được đánh dấu', async () => {
    installFakeLists([
      listDetail({ list_id: 1, name: 'Mock A', items: [laptop, mouse] }),
      listDetail({ list_id: 2, name: 'Mock B', items: [] }),
    ])
    renderAt('/lists/2')
    const nav = await screen.findByRole('navigation', { name: 'Danh sách của bạn' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(['Mock A2 mục', 'Mock B0 mục'])
    expect(links[1]).toHaveAttribute('aria-current', 'page')
    await userEvent.click(links[0] as HTMLElement)
    expect(await screen.findByRole('heading', { level: 2, name: 'Mock A' })).toBeInTheDocument()
  })

  it('màn hình hẹp: chọn danh sách bằng ô chọn ở trên cùng', async () => {
    media.set(false)
    installFakeLists([
      listDetail({ list_id: 1, name: 'Mock A', items: [] }),
      listDetail({ list_id: 2, name: 'Mock B', items: [] }),
    ])
    renderAt('/lists/1')
    const select = await screen.findByRole('combobox', { name: 'Chọn danh sách' })
    expect(select).toHaveValue('1')
    await userEvent.selectOptions(select, '2')
    await waitFor(() => expect(where()).toHaveTextContent('/lists/2'))
    expect(await screen.findByRole('heading', { level: 2, name: 'Mock B' })).toBeInTheDocument()
  })
})

describe('ListsPage · tạo, đổi tên, xóa danh sách', () => {
  it('tạo danh sách mới rồi chuyển tới danh sách đó; tên rỗng bị chặn', async () => {
    const fake = installFakeLists([listDetail({ list_id: 1, items: [] })])
    renderAt('/lists/1')
    await screen.findByRole('heading', { level: 2 })
    await userEvent.click(screen.getByRole('button', { name: 'Tạo danh sách' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Hãy nhập tên danh sách.')
    expect(fake.writes).toEqual([])

    await userEvent.type(screen.getByLabelText('Tên danh sách mới'), '  Học kỳ mới  ')
    await userEvent.click(screen.getByRole('button', { name: 'Tạo danh sách' }))
    await waitFor(() => expect(where()).toHaveTextContent('/lists/2'))
    expect(fake.writes).toEqual(['POST lists {"name":"Học kỳ mới"}'])
    expect(await screen.findByRole('heading', { level: 2, name: 'Học kỳ mới' })).toBeInTheDocument()
  })

  it('tên quá dài (201 ký tự) bị chặn', async () => {
    installFakeLists([listDetail({ items: [] })])
    renderAt('/lists/1')
    await screen.findByRole('heading', { level: 2 })
    fireEvent.change(screen.getByLabelText('Tên danh sách mới'), {
      target: { value: 'a'.repeat(201) },
    })
    await userEvent.click(screen.getByRole('button', { name: 'Tạo danh sách' }))
    expect(screen.getByRole('alert')).toHaveTextContent('dài tối đa 200 ký tự')
  })

  it('đổi tên danh sách: gọi PATCH, tên mới hiện ở tiêu đề và cột bên trái', async () => {
    const fake = installFakeLists([listDetail({ list_id: 1, name: 'Mock cũ', items: [] })])
    renderAt('/lists/1')
    await userEvent.click(await screen.findByRole('button', { name: 'Đổi tên' }))
    const input = await screen.findByLabelText('Tên danh sách')
    expect(input).toHaveValue('Mock cũ')
    await userEvent.clear(input)
    await userEvent.type(input, 'Mock mới')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu' }))

    expect(await screen.findByRole('heading', { level: 2, name: 'Mock mới' })).toBeInTheDocument()
    expect(fake.writes).toEqual(['PATCH lists/1 {"name":"Mock mới"}'])
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(
      within(screen.getByRole('navigation', { name: 'Danh sách của bạn' })).getByText('Mock mới'),
    ).toBeInTheDocument()
  })

  it('đổi tên với tên rỗng hoặc máy chủ từ chối: hiện lỗi, giữ hộp thoại', async () => {
    const fake = installFakeLists([listDetail({ items: [] })])
    renderAt('/lists/1')
    await userEvent.click(await screen.findByRole('button', { name: 'Đổi tên' }))
    const input = await screen.findByLabelText('Tên danh sách')
    await userEvent.clear(input)
    await userEvent.click(screen.getByRole('button', { name: 'Lưu' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Hãy nhập tên danh sách.')

    await userEvent.type(input, 'Tên hợp lệ')
    fake.failWrites = { status: 422, code: 'VALIDATION_ERROR', message: 'Tên không hợp lệ' }
    await userEvent.click(screen.getByRole('button', { name: 'Lưu' }))
    expect(await screen.findByText('Tên không hợp lệ')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('xóa danh sách: luôn hỏi xác nhận; Hủy không xóa', async () => {
    const fake = installFakeLists([listDetail({ name: 'Mock sẽ xóa', items: [] })])
    renderAt('/lists/1')
    await userEvent.click(await screen.findByRole('button', { name: 'Xóa danh sách' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Xóa danh sách "Mock sẽ xóa"?' })
    expect(dialog).toHaveTextContent('không hoàn tác được')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Hủy' }))
    expect(fake.writes).toEqual([])
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('xác nhận xóa: gọi DELETE rồi về /lists (rỗng nên hiện trạng thái rỗng)', async () => {
    const fake = installFakeLists([listDetail({ items: [] })])
    renderAt('/lists/1')
    await userEvent.click(await screen.findByRole('button', { name: 'Xóa danh sách' }))
    await userEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Xóa' }),
    )
    expect(await screen.findByText('Bạn chưa có danh sách mua nào')).toBeInTheDocument()
    expect(fake.writes).toEqual(['DELETE lists/1'])
    expect(where()).toHaveTextContent('/lists')
  })

  it('xóa bị máy chủ từ chối: đóng hộp thoại và báo lỗi, danh sách còn nguyên', async () => {
    const fake = installFakeLists([listDetail({ items: [] })])
    renderAt('/lists/1')
    await userEvent.click(await screen.findByRole('button', { name: 'Xóa danh sách' }))
    fake.failWrites = { status: 500, code: 'INTERNAL_ERROR', message: 'Máy chủ gặp sự cố' }
    await userEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Xóa' }),
    )
    expect(await screen.findByText('Máy chủ gặp sự cố')).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(
      screen.getByRole('heading', { level: 2, name: 'Mock danh sách laptop' }),
    ).toBeInTheDocument()
  })
})

describe('ListsPage · các mục và giá', () => {
  it('hiện từng mục với giá lúc thêm → hiện tại, chênh lệch có chữ, nơi mua, ghi chú và tổng tiền', async () => {
    installFakeLists([listDetail({ items: [laptop, mouse] })])
    renderAt('/lists/1')
    await screen.findByRole('link', { name: 'MockBook Gaming 15' })

    const first = itemCard('MockBook Gaming 15')
    expect(within(first).getByText('Giảm 500.000 ₫')).toBeInTheDocument()
    expect(within(first).getByText('GearVN')).toBeInTheDocument()
    expect(within(first).getByText('(rẻ nhất)')).toBeInTheDocument()
    const second = itemCard('Chuột Mock M1')
    expect(within(second).getByText('Tăng 50.000 ₫')).toBeInTheDocument()
    expect(within(second).getByLabelText('Ghi chú cho Chuột Mock M1')).toHaveValue('màu đen')

    // 2 × 27.490.000 + 1 × 550.000
    expect(screen.getByText('55.530.000 ₫')).toBeInTheDocument()
    expect(
      within(screen.getByRole('region', { name: 'Các mục trong danh sách' })).getByText('2 mục'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/không được tính vào tổng/)).toBeNull()
  })

  it('mục không còn bán: báo rõ và giải thích rằng không tính vào tổng', async () => {
    installFakeLists([listDetail({ items: [laptop, goneItem] })])
    renderAt('/lists/1')
    await screen.findByRole('link', { name: 'Tai nghe Mock H1' })
    expect(
      within(itemCard('Tai nghe Mock H1')).getAllByText('Không còn bán').length,
    ).toBeGreaterThan(0)
    expect(screen.getByText(/Các mục không còn bán không được tính vào tổng/)).toBeInTheDocument()
  })

  it('danh sách chưa có mục nào: trạng thái rỗng kèm hướng dẫn', async () => {
    installFakeLists([listDetail({ items: [] })])
    renderAt('/lists/1')
    expect(await screen.findByText('Danh sách này chưa có sản phẩm')).toBeInTheDocument()
    expect(screen.getByText('0 ₫')).toBeInTheDocument()
  })

  it('tên sản phẩm là liên kết tới trang chi tiết; "Mở trang" an toàn', async () => {
    installFakeLists([
      listDetail({
        items: [
          listItem({
            best_offer: offerView({ url: 'https://mock-gearvn.example/p/12', site: 'gearvn' }),
          }),
        ],
      }),
    ])
    renderAt('/lists/1')
    const link = await screen.findByRole('link', { name: 'MockBook Gaming 15 MG15-4060' })
    expect(link).toHaveAttribute('href', '/products/12')
    const open = screen.getByRole('link', { name: 'Mở trang GearVN' })
    expect(open).toHaveAttribute('rel', 'noopener noreferrer')
    expect(open).toHaveAttribute('target', '_blank')
  })

  it('offer ưu tiên được đánh dấu "ưu tiên", URL nguy hiểm không thành liên kết', async () => {
    installFakeLists([
      listDetail({
        items: [
          listItem({
            preferred_offer_id: 101,
            best_offer: offerView({ offer_id: 101, url: 'javascript:alert(1)' }),
          }),
        ],
      }),
    ])
    renderAt('/lists/1')
    expect(await screen.findByText('(ưu tiên)')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Mở trang/ })).toBeNull()
  })
})

describe('ListsPage · sửa số lượng', () => {
  async function open(items = [laptop, mouse]) {
    const fake = installFakeLists([listDetail({ items })])
    renderAt('/lists/1')
    await screen.findByRole('link', { name: items[0]?.name })
    return fake
  }
  const qty = (name: string) => screen.getByLabelText(`Số lượng của ${name}`)

  it('nút + và − đổi số lượng, gửi PATCH và cập nhật tổng tiền', async () => {
    const fake = await open()
    await userEvent.click(screen.getByRole('button', { name: 'Tăng số lượng MockBook Gaming 15' }))
    await waitFor(() => expect(qty('MockBook Gaming 15')).toHaveValue('3'))
    expect(screen.getByText('83.020.000 ₫')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Giảm số lượng MockBook Gaming 15' }))
    await waitFor(() => expect(qty('MockBook Gaming 15')).toHaveValue('2'))
    expect(fake.writes).toEqual([
      'PATCH lists/1/items/1 {"quantity":3}',
      'PATCH lists/1/items/1 {"quantity":2}',
    ])
  })

  it('nút − tắt ở số lượng 1', async () => {
    await open()
    expect(screen.getByRole('button', { name: 'Giảm số lượng Chuột Mock M1' })).toBeDisabled()
  })

  it('gõ số rồi rời ô (hoặc Enter) thì lưu; không đổi thì không gọi API', async () => {
    const fake = await open()
    const input = qty('MockBook Gaming 15')
    await userEvent.clear(input)
    await userEvent.type(input, '5{Enter}')
    await waitFor(() => expect(fake.writes).toEqual(['PATCH lists/1/items/1 {"quantity":5}']))

    const other = qty('Chuột Mock M1')
    await userEvent.click(other)
    await userEvent.tab()
    expect(fake.writes).toHaveLength(1)
  })

  it.each(['0', '', 'abc', '-1', '1.5', '10001'])(
    'số lượng %j không hợp lệ: không gửi, trả về giá trị cũ',
    async (value) => {
      const fake = await open()
      const input = qty('MockBook Gaming 15')
      await userEvent.clear(input)
      if (value) await userEvent.type(input, value)
      await userEvent.tab()
      expect(fake.writes).toEqual([])
      expect(input).toHaveValue('2')
    },
  )

  it('lạc quan: giao diện đổi ngay khi máy chủ chưa trả lời; máy chủ từ chối thì hoàn tác và báo lỗi', async () => {
    const fake = await open()
    let release: () => void = () => undefined
    fake.hold = new Promise<void>((resolve) => {
      release = resolve
    })
    fake.failWrites = { status: 422, code: 'VALIDATION_ERROR', message: 'Số lượng vượt giới hạn' }

    await userEvent.click(screen.getByRole('button', { name: 'Tăng số lượng MockBook Gaming 15' }))
    await waitFor(() => expect(qty('MockBook Gaming 15')).toHaveValue('3'))
    expect(screen.getByText('83.020.000 ₫')).toBeInTheDocument()

    release()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Không cập nhật được danh sách')
    expect(alert).toHaveTextContent('Số lượng vượt giới hạn')
    await waitFor(() => expect(qty('MockBook Gaming 15')).toHaveValue('2'))
    expect(screen.getByText('55.530.000 ₫')).toBeInTheDocument()
  })
})

describe('ListsPage · ghi chú, nơi mua, xóa mục', () => {
  async function open(items = [laptop, mouse]) {
    const fake = installFakeLists([listDetail({ items })])
    renderAt('/lists/1')
    await screen.findByRole('link', { name: items[0]?.name })
    return fake
  }

  it('thêm ghi chú: lưu khi rời ô; xóa trắng thì xóa ghi chú (null)', async () => {
    const fake = await open()
    const note = screen.getByLabelText('Ghi chú cho MockBook Gaming 15')
    await userEvent.type(note, '  mua khi có voucher  {Enter}')
    await waitFor(() =>
      expect(fake.writes).toEqual(['PATCH lists/1/items/1 {"note":"mua khi có voucher"}']),
    )

    const existing = screen.getByLabelText('Ghi chú cho Chuột Mock M1')
    await userEvent.clear(existing)
    await userEvent.tab()
    await waitFor(() => expect(fake.writes).toContain('PATCH lists/1/items/2 {"note":null}'))
  })

  it('ghi chú không đổi thì không gọi API; quá 500 ký tự thì báo lỗi và không lưu', async () => {
    const fake = await open()
    const existing = screen.getByLabelText('Ghi chú cho Chuột Mock M1')
    await userEvent.click(existing)
    await userEvent.tab()
    expect(fake.writes).toEqual([])

    fireEvent.change(existing, { target: { value: 'a'.repeat(501) } })
    fireEvent.blur(existing)
    expect(screen.getByText('Ghi chú dài tối đa 500 ký tự.')).toBeInTheDocument()
    expect(fake.writes).toEqual([])
  })

  it('"Đổi nơi mua": tải các offer của sản phẩm, chọn một để đặt ưu tiên, "Tự chọn" để bỏ', async () => {
    server.use(
      http.get(apiUrl('products/12'), () =>
        HttpResponse.json(
          productFull({
            offers: [
              offerView({ offer_id: 201, site: 'fptshop', effective_price: 28_000_000 }),
              offerView({ offer_id: 202, site: 'gearvn', effective_price: 27_490_000 }),
              offerView({
                offer_id: 203,
                site: 'anphat',
                effective_price: 29_000_000,
                stock_status: 'out_of_stock',
              }),
            ],
          }),
        ),
      ),
    )
    const fake = await open([laptop])
    await userEvent.click(screen.getByRole('button', { name: 'Đổi nơi mua' }))
    const select = await screen.findByRole('combobox', {
      name: 'Nơi mua ưu tiên cho MockBook Gaming 15',
    })
    await waitFor(() => expect(select).toBeEnabled())
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual([
      'Tự chọn trang rẻ nhất',
      'GearVN · 27.490.000 ₫',
      'FPT Shop · 28.000.000 ₫',
      'An Phát · 29.000.000 ₫ (hết hàng)',
    ])

    await userEvent.selectOptions(select, '201')
    await waitFor(() =>
      expect(fake.writes).toEqual(['PATCH lists/1/items/1 {"preferred_offer_id":201}']),
    )
    await userEvent.selectOptions(select, '')
    await waitFor(() =>
      expect(fake.writes).toContain('PATCH lists/1/items/1 {"preferred_offer_id":null}'),
    )
  })

  it('đổi nơi mua bị từ chối (offer không thuộc sản phẩm): hoàn tác và báo lỗi', async () => {
    const fake = await open([laptop])
    await userEvent.click(screen.getByRole('button', { name: 'Đổi nơi mua' }))
    const select = await screen.findByRole('combobox', { name: /Nơi mua ưu tiên/ })
    await waitFor(() => expect(select).toBeEnabled())
    fake.failWrites = {
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'Offer ưu tiên không thuộc sản phẩm này',
    }
    await userEvent.selectOptions(select, '101')
    expect(await screen.findByText(/Offer ưu tiên không thuộc sản phẩm này/)).toBeInTheDocument()
    await waitFor(() => expect(select).toHaveValue(''))
  })

  it('xóa mục: biến mất ngay (lạc quan), tổng tiền cập nhật, gọi DELETE', async () => {
    const fake = await open()
    await userEvent.click(
      screen.getByRole('button', { name: 'Xóa MockBook Gaming 15 khỏi danh sách' }),
    )
    await waitFor(() =>
      expect(screen.queryByRole('link', { name: 'MockBook Gaming 15' })).toBeNull(),
    )
    const total = screen.getByText('Tổng tiền theo giá hiện tại').parentElement as HTMLElement
    expect(within(total).getByText('550.000 ₫')).toBeInTheDocument()
    expect(fake.writes).toEqual(['DELETE lists/1/items/1'])
    expect(
      within(screen.getByRole('region', { name: 'Các mục trong danh sách' })).getByText('1 mục'),
    ).toBeInTheDocument()
  })

  it('xóa mục bị từ chối: mục quay lại và có thông báo lỗi', async () => {
    const fake = await open()
    fake.failWrites = { status: 500, code: 'INTERNAL_ERROR', message: 'Máy chủ gặp sự cố' }
    await userEvent.click(
      screen.getByRole('button', { name: 'Xóa MockBook Gaming 15 khỏi danh sách' }),
    )
    expect(await screen.findByText('Máy chủ gặp sự cố')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'MockBook Gaming 15' })).toBeInTheDocument()
  })

  it('lỗi mạng khi sửa cũng hoàn tác và hiện thông điệp mạng', async () => {
    await open()
    server.use(http.patch(apiUrl('lists/1/items/1'), () => HttpResponse.error()))
    await userEvent.click(screen.getByRole('button', { name: 'Tăng số lượng MockBook Gaming 15' }))
    expect(await screen.findByText(/Không kết nối được máy chủ/)).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByLabelText('Số lượng của MockBook Gaming 15')).toHaveValue('2'),
    )
  })
})
