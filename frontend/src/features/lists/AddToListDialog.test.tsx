import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { listSummary } from '@/mocks/data'
import { server } from '@/mocks/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AddToListDialog } from './AddToListDialog'

const product = { id: 12, name: 'MockBook Gaming 15' }

function lists(...items: ReturnType<typeof listSummary>[]) {
  server.use(http.get(apiUrl('lists'), () => HttpResponse.json({ items })))
}

function renderDialog(onOpenChange = vi.fn()) {
  renderWithProviders(<AddToListDialog product={product} onOpenChange={onOpenChange} />)
  return onOpenChange
}

const select = () => screen.getByRole('combobox', { name: 'Danh sách' })
const submit = () => screen.getByRole('button', { name: 'Thêm' })

describe('AddToListDialog', () => {
  it('đóng khi product = null', () => {
    renderWithProviders(<AddToListDialog product={null} onOpenChange={vi.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('có tiêu đề, mô tả với tên sản phẩm và mặc định chọn danh sách đầu tiên', async () => {
    lists(listSummary({ list_id: 1, name: 'Mock A' }), listSummary({ list_id: 2, name: 'Mock B' }))
    renderDialog()
    const dialog = await screen.findByRole('dialog', { name: 'Thêm vào danh sách mua' })
    expect(dialog).toHaveTextContent('Thêm "MockBook Gaming 15" vào một danh sách.')
    await waitFor(() => expect(select()).toHaveValue('1'))
    expect(screen.getByRole('option', { name: 'Tạo danh sách mới' })).toBeInTheDocument()
  })

  it('thêm vào danh sách có sẵn: gọi đúng API, báo thành công kèm liên kết', async () => {
    lists(listSummary({ list_id: 3, name: 'Mock đã có' }))
    let request: { url: string; body: unknown } | null = null
    server.use(
      http.post(apiUrl('lists/:id/items'), async ({ request: r }) => {
        request = { url: r.url, body: await r.json() }
        return HttpResponse.json({ item_id: 1 }, { status: 201 })
      }),
    )
    renderDialog()
    await waitFor(() => expect(select()).toHaveValue('3'))
    await userEvent.clear(screen.getByLabelText('Số lượng'))
    await userEvent.type(screen.getByLabelText('Số lượng'), '2')
    await userEvent.click(submit())

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Đã thêm vào danh sách "Mock đã có".',
    )
    expect(request).toMatchObject({ body: { product_id: 12, quantity: 2 } })
    expect(String((request as { url: string } | null)?.url)).toMatch(/lists\/3\/items$/)
    expect(screen.getByRole('link', { name: 'Xem danh sách' })).toHaveAttribute('href', '/lists/3')
  })

  it('chưa có danh sách nào: tự chọn tạo mới, bắt buộc nhập tên rồi tạo và thêm', async () => {
    lists()
    const calls: string[] = []
    server.use(
      http.post(apiUrl('lists'), async ({ request }) => {
        calls.push(`create ${JSON.stringify(await request.json())}`)
        return HttpResponse.json(listSummary({ list_id: 9, name: 'Học kỳ mới' }), { status: 201 })
      }),
      http.post(apiUrl('lists/:id/items'), async ({ request }) => {
        calls.push(`item ${new URL(request.url).pathname} ${JSON.stringify(await request.json())}`)
        return HttpResponse.json({ item_id: 1 }, { status: 201 })
      }),
    )
    renderDialog()
    await waitFor(() => expect(select()).toHaveValue('new'))
    expect(await screen.findByText(/chưa có danh sách nào/)).toBeInTheDocument()

    await userEvent.click(submit())
    expect(screen.getByRole('alert')).toHaveTextContent('Hãy nhập tên danh sách.')
    expect(calls).toEqual([])

    await userEvent.type(screen.getByLabelText('Tên danh sách mới'), '  Học kỳ mới  ')
    await userEvent.click(submit())
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Đã thêm vào danh sách "Học kỳ mới".',
    )
    expect(calls).toEqual([
      'create {"name":"Học kỳ mới"}',
      'item /api/lists/9/items {"product_id":12,"quantity":1}',
    ])
  })

  it('chọn "Tạo danh sách mới" khi đã có danh sách thì hiện ô nhập tên', async () => {
    lists(listSummary({ list_id: 1, name: 'Mock A' }))
    renderDialog()
    await waitFor(() => expect(select()).toHaveValue('1'))
    expect(screen.queryByLabelText('Tên danh sách mới')).toBeNull()
    await userEvent.selectOptions(select(), 'new')
    expect(screen.getByLabelText('Tên danh sách mới')).toBeInTheDocument()
  })

  it.each(['0', '', 'abc', '-1', '1.5', '10001'])(
    'số lượng %j không hợp lệ: nút Thêm bị tắt',
    async (value) => {
      lists(listSummary({ list_id: 1, name: 'Mock A' }))
      renderDialog()
      await waitFor(() => expect(select()).toHaveValue('1'))
      await userEvent.clear(screen.getByLabelText('Số lượng'))
      if (value) await userEvent.type(screen.getByLabelText('Số lượng'), value)
      expect(submit()).toBeDisabled()
      expect(screen.getByLabelText('Số lượng')).toBeInvalid()
    },
  )

  it('máy chủ báo lỗi (404 PRODUCT_NOT_FOUND): hiện thông điệp, giữ hộp thoại để thử lại', async () => {
    lists(listSummary({ list_id: 1, name: 'Mock A' }))
    server.use(
      http.post(apiUrl('lists/:id/items'), () =>
        HttpResponse.json(
          {
            error: {
              code: 'PRODUCT_NOT_FOUND',
              message: 'Không tìm thấy sản phẩm 12',
              details: {},
            },
          },
          { status: 404 },
        ),
      ),
    )
    renderDialog()
    await waitFor(() => expect(select()).toHaveValue('1'))
    await userEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('Không tìm thấy sản phẩm 12')
    expect(submit()).toBeEnabled()
  })

  it('không tải được danh sách: hiện lỗi với nút Thử lại', async () => {
    server.use(http.get(apiUrl('lists'), () => HttpResponse.error()))
    renderDialog()
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.some((alert) => /Không kết nối được máy chủ/.test(alert.textContent ?? ''))).toBe(
      true,
    )
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
  })

  it('Hủy gọi onOpenChange(false)', async () => {
    lists(listSummary())
    const onOpenChange = renderDialog()
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: 'Hủy' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
