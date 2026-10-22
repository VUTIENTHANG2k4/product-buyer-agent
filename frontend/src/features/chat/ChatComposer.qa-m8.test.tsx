import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { ChatComposer } from './ChatComposer'

const MAX = 1000
const box = () => screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Tin nhắn cho agent' })
const sendButton = () => screen.getByRole('button', { name: /^(Gửi|Đang gửi…)$/ })

/** Cha giữ cờ `pending` như trang thật (`send.isPending`) quanh một lần gửi do test điều khiển. */
function Harness({ send }: { send: (message: string) => Promise<void> }) {
  const [pending, setPending] = useState(false)
  return (
    <ChatComposer
      pending={pending}
      onSend={async (message) => {
        setPending(true)
        try {
          await send(message)
        } finally {
          setPending(false)
        }
      }}
    />
  )
}

function deferred() {
  let resolve: () => void = () => undefined
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('ChatComposer · biên độ dài và gửi (QA M8)', () => {
  it('đúng 1.000 ký tự gửi được; 1.001 ký tự bị chặn kèm bộ đếm và thông báo', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(<ChatComposer onSend={onSend} />)
    fireEvent.change(box(), { target: { value: 'a'.repeat(MAX) } })
    expect(sendButton()).toBeEnabled()
    await userEvent.click(sendButton())
    expect(onSend).toHaveBeenCalledWith('a'.repeat(MAX))

    fireEvent.change(box(), { target: { value: 'a'.repeat(MAX + 1) } })
    expect(sendButton()).toBeDisabled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('1001/1000')).toBeInTheDocument()
    fireEvent.keyDown(box(), { key: 'Enter' })
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('tin nhắn tiếng Việt có dấu tổ hợp NFD 999 điểm mã gửi nguyên văn', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(<ChatComposer onSend={onSend} />)
    const text = 'ệ'.normalize('NFD').repeat(333)
    expect(text).toHaveLength(999)
    fireEvent.change(box(), { target: { value: text } })
    await userEvent.click(sendButton())
    expect(onSend).toHaveBeenCalledWith(text)
  })

  it('tin nhắn chứa HTML, emoji và nhiều dòng được gửi nguyên (chỉ cắt hai đầu)', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(<ChatComposer onSend={onSend} />)
    fireEvent.change(box(), { target: { value: '\n  <b>laptop</b> 🎮\n\nrẻ nhất  \n' } })
    await userEvent.click(sendButton())
    expect(onSend).toHaveBeenCalledWith('<b>laptop</b> 🎮\n\nrẻ nhất')
  })

  // BUG-M8-9: độ dài kiểm trên chuỗi CHƯA cắt khoảng trắng, còn thứ gửi đi (và máy chủ kiểm, tối đa
  // 1000) là chuỗi đã cắt. 1.000 ký tự thật + một dấu xuống dòng cuối bị chặn dù hợp lệ. Thấp.
  // XPASS báo đỏ: gỡ `.fails` khi sửa.
  it('1.000 ký tự thật kèm khoảng trắng cuối vẫn gửi được (độ dài tính sau khi cắt)', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(<ChatComposer onSend={onSend} />)
    fireEvent.change(box(), { target: { value: `${'a'.repeat(MAX)}\n` } })
    await userEvent.click(sendButton())
    expect(onSend).toHaveBeenCalledWith('a'.repeat(MAX))
  })

  it('bấm Enter hai lần trong lúc lần gửi đầu chưa xong chỉ gửi một lần', async () => {
    const gate = deferred()
    const send = vi.fn(() => gate.promise)
    render(<Harness send={send} />)
    await userEvent.type(box(), 'laptop{Enter}')
    await screen.findByRole('button', { name: 'Đang gửi…' })
    await userEvent.type(box(), '{Enter}')
    expect(send).toHaveBeenCalledTimes(1)
    gate.resolve()
    await waitFor(() => expect(box()).toHaveValue(''))
  })

  it('gửi lỗi: nội dung được giữ và gửi lại được', async () => {
    const send = vi
      .fn<(message: string) => Promise<void>>()
      .mockRejectedValueOnce(new Error('mạng'))
      .mockResolvedValueOnce(undefined)
    render(<Harness send={send} />)
    await userEvent.type(box(), 'laptop{Enter}')
    await waitFor(() => expect(sendButton()).toHaveTextContent('Gửi'))
    expect(box()).toHaveValue('laptop')
    await userEvent.click(sendButton())
    await waitFor(() => expect(box()).toHaveValue(''))
    expect(send).toHaveBeenCalledTimes(2)
  })

  // BUG-M8-10: ô nhập vẫn gõ được trong lúc tin đang gửi, nhưng khi gửi xong `setValue('')` xóa cả
  // phần người dùng vừa gõ cho tin kế tiếp. Chỉ xóa khi nội dung vẫn đúng là tin đã gửi. Thấp/trung bình
  // (mất chữ khi mạng chậm). XPASS báo đỏ: gỡ `.fails` khi sửa.
  it('chữ gõ thêm trong lúc tin trước đang gửi không bị xóa khi gửi xong', async () => {
    const gate = deferred()
    render(<Harness send={() => gate.promise} />)
    await userEvent.type(box(), 'laptop{Enter}')
    await screen.findByRole('button', { name: 'Đang gửi…' })
    await userEvent.clear(box())
    await userEvent.type(box(), 'chuột không dây')
    gate.resolve()
    await waitFor(() => expect(sendButton()).toHaveTextContent('Gửi'))
    expect(box()).toHaveValue('chuột không dây')
  })
})
