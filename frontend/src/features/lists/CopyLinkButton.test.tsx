import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { strings } from '@/lib/strings'
import { renderWithProviders } from '@/test/renderWithProviders'
import { COPIED_RESET_MS, CopyLinkButton } from './CopyLinkButton'

const text = strings.lists
const expectedUrl = `${window.location.origin}/lists/7`

function stubClipboard(writeText: (value: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn(writeText) },
  })
  return navigator.clipboard.writeText as ReturnType<typeof vi.fn>
}

afterEach(() => {
  Reflect.deleteProperty(navigator, 'clipboard')
  vi.useRealTimers()
})

describe('CopyLinkButton', () => {
  it('chép URL tuyệt đối của trang danh sách và báo "Đã sao chép link"', async () => {
    const writeText = stubClipboard(() => Promise.resolve())
    renderWithProviders(<CopyLinkButton listId={7} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    expect(writeText).toHaveBeenCalledWith(expectedUrl)
    expect(screen.getByRole('button', { name: text.linkCopied })).toBeInTheDocument()
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent(text.linkCopied)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('trở lại chữ "Sao chép link" sau một lúc', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    stubClipboard(() => Promise.resolve())
    renderWithProviders(<CopyLinkButton listId={7} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))
    expect(screen.getByRole('button', { name: text.linkCopied })).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(COPIED_RESET_MS)
    })

    expect(screen.getByRole('button', { name: text.copyLink })).toBeInTheDocument()
  })

  it('clipboard từ chối: hiện ô chứa URL để chép thủ công', async () => {
    stubClipboard(() => Promise.reject(new Error('denied')))
    renderWithProviders(<CopyLinkButton listId={7} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(text.copyFailed)
    const field = screen.getByRole('textbox', { name: text.shareUrl })
    expect(field).toHaveValue(expectedUrl)
    expect(field).toHaveAttribute('readonly')
  })

  it('không có clipboard (ngoài secure context): cũng hiện ô URL', async () => {
    Reflect.deleteProperty(navigator, 'clipboard')
    renderWithProviders(<CopyLinkButton listId={7} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    expect(screen.getByRole('textbox', { name: text.shareUrl })).toHaveValue(expectedUrl)
  })

  it('chép lại được sau khi lỗi: ô URL biến mất khi thành công', async () => {
    let fail = true
    stubClipboard(() => (fail ? Promise.reject(new Error('denied')) : Promise.resolve()))
    renderWithProviders(<CopyLinkButton listId={7} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))
    expect(screen.getByRole('alert')).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: text.linkCopied })).toBeInTheDocument()
  })
})
