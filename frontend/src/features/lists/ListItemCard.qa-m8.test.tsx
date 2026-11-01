import { fireEvent, screen } from '@testing-library/react'
import { useState } from 'react'
import userEvent from '@testing-library/user-event'
import { listItem, offerView } from '@/mocks/data'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ListItemCard, MAX_ITEM_QUANTITY } from './ListItemCard'

const NAME = 'Laptop Mock Đà Nẵng'

function setup(overrides: Parameters<typeof listItem>[0] = {}) {
  const onUpdate = vi.fn()
  const onRemove = vi.fn()
  const item = listItem({ item_id: 7, name: NAME, quantity: 3, ...overrides })
  const view = renderWithProviders(
    <ul>
      <ListItemCard item={item} onUpdate={onUpdate} onRemove={onRemove} />
    </ul>,
  )
  const quantity = () =>
    screen.getByRole<HTMLInputElement>('textbox', { name: `Số lượng của ${NAME}` })
  const note = () => screen.getByRole<HTMLInputElement>('textbox', { name: `Ghi chú cho ${NAME}` })
  return { onUpdate, onRemove, quantity, note, ...view }
}

async function typeInto(input: HTMLInputElement, text: string) {
  await userEvent.clear(input)
  if (text !== '') await userEvent.type(input, text)
}

describe('ListItemCard · số lượng (QA M8)', () => {
  it.each([
    ['0', 'số 0'],
    ['-3', 'số âm'],
    [String(MAX_ITEM_QUANTITY + 1), 'vượt trần 10.000'],
    ['1e3', 'ký hiệu khoa học'],
    ['1.5', 'số lẻ'],
    ['1,5', 'số lẻ dấu phẩy'],
    ['abc', 'chữ'],
    ['5a', 'số kèm chữ'],
    ['99999999999999999999', 'số cực lớn'],
    ['٣', 'chữ số Ả Rập'],
    ['+5', 'dấu cộng'],
    ['', 'ô trống'],
  ])(
    'gõ %j (%s) rồi Enter: không gửi cập nhật, ô trả về số lượng cũ, ô đánh dấu sai khi đang gõ',
    async (text) => {
      const { onUpdate, quantity } = setup()
      await typeInto(quantity(), text)
      expect(quantity()).toHaveAttribute('aria-invalid', 'true')
      await userEvent.keyboard('{Enter}')
      expect(onUpdate).not.toHaveBeenCalled()
      expect(quantity()).toHaveValue('3')
      expect(quantity()).toHaveAttribute('aria-invalid', 'false')
    },
  )

  it.each([
    ['1', 1],
    ['10000', 10_000],
    ['0010', 10],
    ['7', 7],
  ])('gõ %j rồi Enter gửi đúng số lượng %d', async (text, expected) => {
    const { onUpdate, quantity } = setup()
    await typeInto(quantity(), text)
    await userEvent.keyboard('{Enter}')
    expect(onUpdate).toHaveBeenCalledTimes(1)
    expect(onUpdate).toHaveBeenCalledWith(7, { quantity: expected })
  })

  it('gõ đúng số lượng hiện tại rồi Enter hoặc rời ô: không gửi gì', async () => {
    const { onUpdate, quantity } = setup()
    await typeInto(quantity(), '3')
    await userEvent.keyboard('{Enter}')
    fireEvent.blur(quantity())
    expect(onUpdate).not.toHaveBeenCalled()
  })

  it('rời ô khi nhập sai: trả về số cũ và không gửi', async () => {
    const { onUpdate, quantity } = setup()
    await typeInto(quantity(), '0')
    fireEvent.blur(quantity())
    expect(onUpdate).not.toHaveBeenCalled()
    expect(quantity()).toHaveValue('3')
  })

  it('nút − tắt ở số lượng 1 và nút + tắt ở trần 10.000; ở giữa bấm gửi ±1', async () => {
    const low = setup({ quantity: 1 })
    expect(screen.getByRole('button', { name: `Giảm số lượng ${NAME}` })).toBeDisabled()
    low.unmount()

    const high = setup({ quantity: MAX_ITEM_QUANTITY })
    expect(screen.getByRole('button', { name: `Tăng số lượng ${NAME}` })).toBeDisabled()
    high.unmount()

    const mid = setup({ quantity: 5 })
    await userEvent.click(screen.getByRole('button', { name: `Tăng số lượng ${NAME}` }))
    await userEvent.click(screen.getByRole('button', { name: `Giảm số lượng ${NAME}` }))
    expect(mid.onUpdate.mock.calls).toEqual([
      [7, { quantity: 6 }],
      [7, { quantity: 4 }],
    ])
  })

  it('số lượng đổi từ ngoài (hoàn tác sau lỗi) cập nhật ô nhập và xóa trạng thái sai', async () => {
    function Harness() {
      const [quantity, setQuantity] = useState(3)
      return (
        <ul>
          <ListItemCard
            item={listItem({ item_id: 7, name: NAME, quantity })}
            onUpdate={vi.fn()}
            onRemove={vi.fn()}
          />
          <button type="button" onClick={() => setQuantity(2)}>
            hoàn tác
          </button>
        </ul>
      )
    }
    renderWithProviders(<Harness />)
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: `Số lượng của ${NAME}` })
    await typeInto(input, '9')
    expect(input).toHaveValue('9')
    await userEvent.click(screen.getByRole('button', { name: 'hoàn tác' }))
    expect(input).toHaveValue('2')
    expect(input).toHaveAttribute('aria-invalid', 'false')
  })
})

describe('ListItemCard · ghi chú (QA M8)', () => {
  it('đúng 500 ký tự được lưu; 501 ký tự bị chặn kèm thông báo', async () => {
    const ok = setup()
    fireEvent.change(ok.note(), { target: { value: 'a'.repeat(500) } })
    await userEvent.type(ok.note(), '{Enter}')
    expect(ok.onUpdate).toHaveBeenCalledWith(7, { note: 'a'.repeat(500) })
    expect(screen.queryByText('Ghi chú dài tối đa 500 ký tự.')).toBeNull()
    ok.unmount()

    const bad = setup()
    fireEvent.change(bad.note(), { target: { value: 'a'.repeat(501) } })
    expect(screen.getByText('Ghi chú dài tối đa 500 ký tự.')).toBeInTheDocument()
    expect(bad.note()).toHaveAttribute('aria-invalid', 'true')
    await userEvent.type(bad.note(), '{Enter}')
    fireEvent.blur(bad.note())
    expect(bad.onUpdate).not.toHaveBeenCalled()
  })

  it('ghi chú tiếng Việt NFD 500 ký tự (dấu tổ hợp tính từng điểm mã) được xử lý như văn bản thường', async () => {
    const note = 'ệ'.normalize('NFD').repeat(250) // 3 điểm mã mỗi chữ → 750 đơn vị
    const { note: input, onUpdate } = setup()
    fireEvent.change(input(), { target: { value: note } })
    await userEvent.type(input(), '{Enter}')
    expect(onUpdate).not.toHaveBeenCalled()
    expect(screen.getByText('Ghi chú dài tối đa 500 ký tự.')).toBeInTheDocument()
  })

  // BUG-M8-7: độ dài đo bằng đơn vị UTF-16 (`text.length`) còn máy chủ (Pydantic) đo bằng điểm mã. 300
  // emoji là 300 ký tự với máy chủ (≤ 500, hợp lệ) nhưng 600 đơn vị với giao diện nên bị chặn. Rất
  // thấp: chỉ gặp khi ghi chú dùng nhiều emoji. XPASS báo đỏ: gỡ `.fails` khi sửa.
  it('300 emoji (300 điểm mã, 600 đơn vị UTF-16) vẫn nằm trong giới hạn 500 ký tự', async () => {
    const note = '\u{1F600}'.repeat(300)
    expect(Array.from(note)).toHaveLength(300)
    const { note: input, onUpdate } = setup()
    fireEvent.change(input(), { target: { value: note } })
    await userEvent.type(input(), '{Enter}')
    expect(onUpdate).toHaveBeenCalledWith(7, { note })
  })

  it('ghi chú toàn khoảng trắng xóa ghi chú cũ (gửi null); không có ghi chú cũ thì không gửi gì', async () => {
    const withNote = setup({ note: 'màu đen' })
    await typeInto(withNote.note(), '   ')
    await userEvent.keyboard('{Enter}')
    expect(withNote.onUpdate).toHaveBeenCalledWith(7, { note: null })
    withNote.unmount()

    const without = setup({ note: null })
    await typeInto(without.note(), '   ')
    await userEvent.keyboard('{Enter}')
    expect(without.onUpdate).not.toHaveBeenCalled()
  })

  it('cắt khoảng trắng hai đầu trước khi gửi; giữ nguyên dấu tiếng Việt, emoji và ký tự đặc biệt', async () => {
    const { note, onUpdate } = setup()
    await typeInto(note(), '  Đã chọn màu xám 🎨 <b>"x"</b> & y  ')
    await userEvent.keyboard('{Enter}')
    expect(onUpdate).toHaveBeenCalledWith(7, { note: 'Đã chọn màu xám 🎨 <b>"x"</b> & y' })
  })

  it('ghi chú không đổi so với bản đã lưu thì không gửi lại', async () => {
    const { note, onUpdate } = setup({ note: 'màu đen' })
    await typeInto(note(), '  màu đen ')
    await userEvent.keyboard('{Enter}')
    fireEvent.blur(note())
    expect(onUpdate).not.toHaveBeenCalled()
  })
})

describe('ListItemCard · dữ liệu lạ (QA M8)', () => {
  it('tên chứa HTML và 2.000 ký tự được hiện như văn bản; nhãn nút xóa dùng đúng tên', async () => {
    const name = `<img src=x onerror=alert(1)> ${'Dài '.repeat(499)}Dài`
    const onRemove = vi.fn()
    const { container } = renderWithProviders(
      <ul>
        <ListItemCard
          item={listItem({ item_id: 9, name })}
          onUpdate={vi.fn()}
          onRemove={onRemove}
        />
      </ul>,
    )
    expect(container.querySelector('img')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: `Xóa ${name} khỏi danh sách` }))
    expect(onRemove).toHaveBeenCalledWith(9)
  })

  it('offer tốt nhất có URL javascript: không thành liên kết "Mở trang"', () => {
    setup({ best_offer: offerView({ url: 'javascript:alert(1)' }) })
    expect(screen.queryByRole('link', { name: /Mở trang/ })).toBeNull()
  })

  it('không còn offer (best_offer null, giá hiện tại null): hiện "không còn bán", không lỗi', () => {
    setup({ best_offer: null, current_price: null, price_delta: null })
    expect(screen.getByRole('textbox', { name: `Số lượng của ${NAME}` })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Mở trang/ })).toBeNull()
  })

  it('giá 5 tỷ hiện đủ chữ số có dấu chấm', () => {
    setup({ current_price: 5_000_000_000, price_at_add: 5_000_000_000, price_delta: 0 })
    expect(screen.getAllByText(/5\.000\.000\.000/).length).toBeGreaterThan(0)
  })
})
