import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatComposer } from './ChatComposer'

const box = () => screen.getByRole('textbox', { name: 'Tin nhắn cho agent' })
const sendButton = () => screen.getByRole('button', { name: /^(Gửi|Đang gửi…)$/ })

describe('ChatComposer', () => {
  it('có nhãn cho ô nhập, nút Gửi tắt khi rỗng hoặc chỉ có khoảng trắng', async () => {
    render(<ChatComposer onSend={vi.fn()} />)
    expect(sendButton()).toBeDisabled()
    await userEvent.type(box(), '   ')
    expect(sendButton()).toBeDisabled()
    await userEvent.type(box(), 'laptop')
    expect(sendButton()).toBeEnabled()
  })

  it('Enter gửi tin đã cắt khoảng trắng rồi xóa ô nhập', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(<ChatComposer onSend={onSend} />)
    await userEvent.type(box(), '  laptop gaming dưới 30 triệu  {Enter}')
    expect(onSend).toHaveBeenCalledExactlyOnceWith('laptop gaming dưới 30 triệu')
    await waitFor(() => expect(box()).toHaveValue(''))
  })

  it('Shift+Enter xuống dòng và không gửi', async () => {
    const onSend = vi.fn()
    render(<ChatComposer onSend={onSend} />)
    await userEvent.type(box(), 'dòng 1{Shift>}{Enter}{/Shift}dòng 2')
    expect(onSend).not.toHaveBeenCalled()
    expect(box()).toHaveValue('dòng 1\ndòng 2')
  })

  it('Enter khi đang gõ dấu bằng bộ gõ (IME) không gửi', () => {
    const onSend = vi.fn()
    render(<ChatComposer onSend={onSend} />)
    fireEvent.change(box(), { target: { value: 'chuột' } })
    fireEvent.keyDown(box(), { key: 'Enter', isComposing: true })
    expect(onSend).not.toHaveBeenCalled()
  })

  it('bấm nút Gửi cũng gửi', async () => {
    const onSend = vi.fn()
    render(<ChatComposer onSend={onSend} />)
    await userEvent.type(box(), 'tai nghe')
    await userEvent.click(sendButton())
    expect(onSend).toHaveBeenCalledWith('tai nghe')
  })

  it('đúng 1000 ký tự gửi được, 1001 ký tự thì chặn và báo lỗi', () => {
    const onSend = vi.fn()
    render(<ChatComposer onSend={onSend} />)
    fireEvent.change(box(), { target: { value: 'a'.repeat(1000) } })
    expect(sendButton()).toBeEnabled()
    expect(screen.getByText('1000/1000')).toBeInTheDocument()

    fireEvent.change(box(), { target: { value: 'a'.repeat(1001) } })
    expect(sendButton()).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Tin nhắn dài tối đa 1000 ký tự.')
    expect(box()).toBeInvalid()
    fireEvent.keyDown(box(), { key: 'Enter' })
    expect(onSend).not.toHaveBeenCalled()
  })

  it('bộ đếm chỉ hiện khi gần tới giới hạn', () => {
    render(<ChatComposer onSend={vi.fn()} />)
    fireEvent.change(box(), { target: { value: 'a'.repeat(100) } })
    expect(screen.queryByText('100/1000')).toBeNull()
  })

  it('gửi lỗi thì giữ nguyên nội dung để thử lại', async () => {
    const onSend = vi.fn().mockRejectedValue(new Error('hỏng'))
    render(<ChatComposer onSend={onSend} />)
    await userEvent.type(box(), 'laptop{Enter}')
    await waitFor(() => expect(onSend).toHaveBeenCalled())
    expect(box()).toHaveValue('laptop')
  })

  it('hiện lỗi của lần gửi trước dưới ô nhập', () => {
    render(<ChatComposer onSend={vi.fn()} error="Không gọi được LLM" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Không gọi được LLM')
    expect(box()).toBeInvalid()
  })

  it('đang gửi hoặc bị tắt thì không gửi được', async () => {
    const onSend = vi.fn()
    const { rerender } = render(<ChatComposer onSend={onSend} pending />)
    expect(sendButton()).toHaveTextContent('Đang gửi…')
    expect(sendButton()).toBeDisabled()

    rerender(<ChatComposer onSend={onSend} disabled />)
    expect(box()).toBeDisabled()
    expect(sendButton()).toBeDisabled()
  })

  it('đặt được gợi ý nhập khác cho câu hỏi tiếp theo', () => {
    render(<ChatComposer onSend={vi.fn()} placeholder="Hỏi tiếp…" />)
    expect(screen.getByPlaceholderText('Hỏi tiếp…')).toBeInTheDocument()
  })
})
