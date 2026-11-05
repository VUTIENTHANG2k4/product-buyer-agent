import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, MemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { strings } from '@/lib/strings'
import { renderWithProviders } from '@/test/renderWithProviders'
import { COPIED_RESET_MS, CopyLinkButton } from './CopyLinkButton'

const text = strings.lists

function stubClipboard(writeText: (value: string) => Promise<void>) {
  const fn = vi.fn(writeText)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: fn } })
  return fn
}

function deferred() {
  let resolve!: () => void
  let reject!: (error: Error) => void
  const promise = new Promise<void>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

afterEach(() => {
  Reflect.deleteProperty(navigator, 'clipboard')
  vi.useRealTimers()
})

describe('CopyLinkButton · QA X3', () => {
  it('bấm nhanh hai lần: chép hai lần cùng URL, chỉ còn một hẹn giờ, trở lại sau đúng 2 s từ lần cuối', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    // userEvent.setup() gắn clipboard giả của nó: stub sau khi setup.
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const writeText = stubClipboard(() => Promise.resolve())
    renderWithProviders(<CopyLinkButton listId={3} />)

    await user.click(screen.getByRole('button', { name: text.copyLink }))
    act(() => {
      vi.advanceTimersByTime(COPIED_RESET_MS - 500)
    })
    await user.click(screen.getByRole('button', { name: text.linkCopied }))

    expect(writeText).toHaveBeenCalledTimes(2)
    expect(writeText).toHaveBeenNthCalledWith(2, `${window.location.origin}/lists/3`)
    expect(vi.getTimerCount()).toBe(1)
    act(() => {
      vi.advanceTimersByTime(COPIED_RESET_MS - 100)
    })
    // Hẹn giờ của lần bấm đầu đã bị hủy: vẫn "Đã sao chép".
    expect(screen.getByRole('button', { name: text.linkCopied })).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(screen.getByRole('button', { name: text.copyLink })).toBeInTheDocument()
  })

  it('gỡ component khi đang hiện "Đã sao chép": hủy hẹn giờ, không lỗi', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    stubClipboard(() => Promise.resolve())
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    const view = renderWithProviders(<CopyLinkButton listId={3} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))
    expect(vi.getTimerCount()).toBe(1)
    view.unmount()

    expect(vi.getTimerCount()).toBe(0)
    act(() => {
      vi.advanceTimersByTime(COPIED_RESET_MS * 2)
    })
    expect(errors).not.toHaveBeenCalled()
    errors.mockRestore()
  })

  // BUG-X3-2 (đã sửa): gỡ component khi writeText chưa xong, promise resolve sau đó không được
  // đặt hẹn giờ mới vì cleanup đã chạy và không còn ai hủy.
  it('gỡ component khi clipboard chưa xong: không để lại hẹn giờ mồ côi', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const pending = deferred()
    stubClipboard(() => pending.promise)
    const view = renderWithProviders(<CopyLinkButton listId={3} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))
    view.unmount()
    await act(async () => {
      pending.resolve()
      await pending.promise
    })

    expect(vi.getTimerCount()).toBe(0)
  })

  // BUG-X3-3 (đã sửa): hai lần bấm chồng nhau, lần đầu bị từ chối SAU lần hai thành công không
  // được báo lỗi + hiện ô URL vì link đã được chép.
  it('lần bấm trước bị từ chối muộn không ghi đè kết quả lần bấm sau đã thành công', async () => {
    const first = deferred()
    let call = 0
    stubClipboard(() => {
      call += 1
      return call === 1 ? first.promise : Promise.resolve()
    })
    renderWithProviders(<CopyLinkButton listId={3} />)
    const button = screen.getByRole('button', { name: text.copyLink })

    await userEvent.click(button)
    await userEvent.click(button)
    expect(screen.getByRole('button', { name: text.linkCopied })).toBeInTheDocument()
    await act(async () => {
      first.reject(new Error('denied'))
      await first.promise.catch(() => undefined)
    })

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('đổi listId: chép URL của danh sách mới', async () => {
    const writeText = stubClipboard(() => Promise.resolve())
    const view = render(
      <MemoryRouter>
        <CopyLinkButton listId={4} />
      </MemoryRouter>,
    )
    view.rerender(
      <MemoryRouter>
        <CopyLinkButton listId={5} />
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/lists/5`)
  })

  it('đổi listId khi đang hiện ô URL dự phòng: ô cập nhật URL của danh sách mới', async () => {
    stubClipboard(() => Promise.reject(new Error('denied')))
    const view = render(
      <MemoryRouter>
        <CopyLinkButton listId={4} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))
    expect(screen.getByRole('textbox', { name: text.shareUrl })).toHaveValue(
      `${window.location.origin}/lists/4`,
    )

    view.rerender(
      <MemoryRouter>
        <CopyLinkButton listId={5} />
      </MemoryRouter>,
    )

    // Cùng một instance nên trạng thái lỗi còn giữ; điều quan trọng là ô không còn URL cũ.
    expect(screen.getByRole('textbox', { name: text.shareUrl })).toHaveValue(
      `${window.location.origin}/lists/5`,
    )
    expect(screen.queryByDisplayValue(`${window.location.origin}/lists/4`)).toBeNull()
  })

  it('router có basename: URL chép gồm basename', async () => {
    const writeText = stubClipboard(() => Promise.resolve())
    const router = createMemoryRouter(
      [{ path: '/lists/:id', element: <CopyLinkButton listId={8} /> }],
      { basename: '/app', initialEntries: ['/app/lists/8'] },
    )
    render(<RouterProvider router={router} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/app/lists/8`)
  })

  it('ô URL dự phòng chọn sẵn toàn bộ chữ để chép thủ công', async () => {
    Reflect.deleteProperty(navigator, 'clipboard')
    renderWithProviders(<CopyLinkButton listId={12} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    const field = screen.getByRole<HTMLInputElement>('textbox', { name: text.shareUrl })
    expect(field).toHaveFocus()
    expect(field.selectionStart).toBe(0)
    expect(field.selectionEnd).toBe(field.value.length)
  })

  it('clipboard ném lỗi đồng bộ (không trả Promise): vẫn hiện ô URL', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: () => {
          throw new DOMException('Document is not focused.', 'NotAllowedError')
        },
      },
    })
    renderWithProviders(<CopyLinkButton listId={3} />)

    await userEvent.click(screen.getByRole('button', { name: text.copyLink }))

    expect(screen.getByRole('alert')).toHaveTextContent(text.copyFailed)
  })
})
