import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import { server } from '@/mocks/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { CreateAlertDialog, type AlertProduct } from './CreateAlertDialog'

const product: AlertProduct = { id: 12, name: 'MockBook Gaming 15', currentPrice: 27_490_000 }

function renderDialog(over: Partial<AlertProduct> = {}, onOpenChange = vi.fn()) {
  renderWithProviders(
    <CreateAlertDialog product={{ ...product, ...over }} onOpenChange={onOpenChange} />,
  )
  return onOpenChange
}

function capture() {
  const holder: { body?: unknown } = {}
  server.use(
    http.post(apiUrl('alerts'), async ({ request }) => {
      holder.body = await request.json()
      return HttpResponse.json({ alert_id: 1 }, { status: 201 })
    }),
  )
  return holder
}

const target = () => screen.getByLabelText('Ngưỡng giá (₫)')
const submit = () => screen.getByRole('button', { name: 'Tạo cảnh báo' })

describe('CreateAlertDialog', () => {
  it('đóng khi product = null', () => {
    renderWithProviders(<CreateAlertDialog product={null} onOpenChange={vi.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('hiện giá hiện tại, mô tả theo tên sản phẩm và hai gợi ý −5%/−10%', async () => {
    renderDialog()
    const dialog = await screen.findByRole('dialog', { name: 'Báo khi giảm giá' })
    expect(dialog).toHaveTextContent('Giá thấp nhất hiện tại: 27.490.000 ₫')
    expect(dialog).toHaveTextContent('"MockBook Gaming 15"')
    expect(screen.getByRole('button', { name: '−5% (26.116.000 ₫)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '−10% (24.741.000 ₫)' })).toBeInTheDocument()
  })

  it('bấm gợi ý điền ngưỡng; gửi đúng số nguyên VND, kênh/nơi nhận bỏ trống thì không gửi', async () => {
    const sent = capture()
    renderDialog()
    await userEvent.click(await screen.findByRole('button', { name: /^−10%/ }))
    expect(target()).toHaveValue('24741000')
    await userEvent.click(submit())

    expect(await screen.findByRole('status')).toHaveTextContent('Đã tạo cảnh báo giá.')
    expect(sent.body).toEqual({ product_id: 12, target_price: 24_741_000 })
    expect(screen.getByRole('link', { name: 'Xem cảnh báo' })).toHaveAttribute('href', '/alerts')
  })

  it('nhập ngưỡng có dấu phân nhóm, chọn kênh và nơi nhận', async () => {
    const sent = capture()
    renderDialog()
    await userEvent.type(await screen.findByLabelText('Ngưỡng giá (₫)'), '25.000.000')
    await userEvent.selectOptions(screen.getByLabelText('Kênh nhận thông báo'), 'telegram')
    await userEvent.type(screen.getByLabelText('Nơi nhận (tùy chọn)'), '  123456  ')
    await userEvent.click(submit())
    await screen.findByRole('status')
    expect(sent.body).toEqual({
      product_id: 12,
      target_price: 25_000_000,
      channel: 'telegram',
      destination: '123456',
    })
  })

  it.each(['', 'abc', '27.5', '0', '-1', '25 triệu'])(
    'ngưỡng %j không hợp lệ: nút tạo bị tắt',
    async (value) => {
      renderDialog()
      await screen.findByRole('dialog')
      if (value) await userEvent.type(target(), value)
      expect(submit()).toBeDisabled()
      if (value) expect(target()).toBeInvalid()
    },
  )

  it('chưa có giá hiện tại: không có gợi ý và không có dòng giá', async () => {
    renderDialog({ currentPrice: null })
    await screen.findByRole('dialog')
    expect(screen.queryByText(/Giá thấp nhất hiện tại/)).toBeNull()
    expect(screen.queryByRole('button', { name: /^−/ })).toBeNull()
  })

  it('409 DUPLICATE_ALERT: hiện thông điệp của máy chủ và giữ hộp thoại để sửa ngưỡng', async () => {
    server.use(
      http.post(apiUrl('alerts'), () =>
        HttpResponse.json(
          {
            error: {
              code: 'DUPLICATE_ALERT',
              message: 'Đã có cảnh báo cùng ngưỡng',
              details: {},
            },
          },
          { status: 409 },
        ),
      ),
    )
    renderDialog()
    await userEvent.type(await screen.findByLabelText('Ngưỡng giá (₫)'), '25000000')
    await userEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('Đã có cảnh báo cùng ngưỡng')
    expect(submit()).toBeEnabled()
  })

  it('422 (nơi nhận chưa cấu hình): hiện thông điệp, không báo thành công', async () => {
    server.use(
      http.post(apiUrl('alerts'), () =>
        HttpResponse.json(
          { error: { code: 'VALIDATION_ERROR', message: 'Chưa cấu hình nơi nhận', details: {} } },
          { status: 422 },
        ),
      ),
    )
    renderDialog()
    await userEvent.type(await screen.findByLabelText('Ngưỡng giá (₫)'), '25000000')
    await userEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('Chưa cấu hình nơi nhận')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('đang gửi: nút hiện "Đang tạo…" và bị tắt', async () => {
    let release: () => void = () => undefined
    server.use(
      http.post(apiUrl('alerts'), async () => {
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return HttpResponse.json({ alert_id: 1 }, { status: 201 })
      }),
    )
    renderDialog()
    await userEvent.type(await screen.findByLabelText('Ngưỡng giá (₫)'), '25000000')
    await userEvent.click(submit())
    expect(await screen.findByRole('button', { name: 'Đang tạo…' })).toBeDisabled()
    release()
    await screen.findByRole('status')
  })

  it('Hủy gọi onOpenChange(false)', async () => {
    const onOpenChange = renderDialog()
    await userEvent.click(await screen.findByRole('button', { name: 'Hủy' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
