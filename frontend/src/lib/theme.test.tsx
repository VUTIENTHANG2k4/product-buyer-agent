import { act, renderHook } from '@testing-library/react'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { applyTheme, readStoredTheme, resolveTheme, THEME_STORAGE_KEY, useTheme } from './theme'

let media: MatchMediaControl

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.classList.remove('dark')
  media = mockMatchMedia(false)
})

afterEach(() => {
  media.restore()
  vi.restoreAllMocks()
})

describe('resolveTheme', () => {
  it.each([
    ['light', true, 'light'],
    ['dark', false, 'dark'],
    ['system', true, 'dark'],
    ['system', false, 'light'],
  ] as const)('%s khi hệ thống tối=%s → %s', (mode, prefersDark, expected) => {
    expect(resolveTheme(mode, prefersDark)).toBe(expected)
  })
})

describe('readStoredTheme', () => {
  it('mặc định theo hệ thống khi chưa lưu hoặc giá trị lạ', () => {
    expect(readStoredTheme()).toBe('system')
    window.localStorage.setItem(THEME_STORAGE_KEY, 'neon')
    expect(readStoredTheme()).toBe('system')
  })

  it('đọc giá trị hợp lệ đã lưu', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    expect(readStoredTheme()).toBe('dark')
  })

  it('localStorage ném lỗi (bị chặn) thì vẫn dùng chế độ theo hệ thống', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('bị chặn', 'SecurityError')
    })
    expect(readStoredTheme()).toBe('system')
  })
})

describe('applyTheme', () => {
  it('chế độ tối bật lớp dark, chế độ sáng gỡ lớp dark', () => {
    applyTheme('dark')
    expect(document.documentElement).toHaveClass('dark')
    applyTheme('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('theo hệ thống: dùng prefers-color-scheme', () => {
    media.set(true)
    applyTheme('system')
    expect(document.documentElement).toHaveClass('dark')
  })

  it('matchMedia ném lỗi thì dùng chế độ sáng', () => {
    window.matchMedia = () => {
      throw new Error('không hỗ trợ')
    }
    applyTheme('system')
    expect(document.documentElement).not.toHaveClass('dark')
  })
})

describe('useTheme', () => {
  it('đổi chế độ thì áp dụng ngay và lưu lại', () => {
    const { result } = renderHook(() => useTheme())
    expect(result.current.mode).toBe('system')

    act(() => result.current.setMode('dark'))
    expect(result.current.mode).toBe('dark')
    expect(document.documentElement).toHaveClass('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')

    act(() => result.current.setMode('light'))
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('đổi được dù không lưu được vào localStorage', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('đầy', 'QuotaExceededError')
    })
    const { result } = renderHook(() => useTheme())
    act(() => result.current.setMode('dark'))
    expect(document.documentElement).toHaveClass('dark')
  })

  it('ở chế độ theo hệ thống thì tự đổi khi hệ điều hành đổi, và ngừng theo dõi khi chọn cố định', () => {
    const { result } = renderHook(() => useTheme())
    act(() => media.set(true))
    expect(document.documentElement).toHaveClass('dark')

    act(() => result.current.setMode('light'))
    act(() => media.set(true))
    expect(document.documentElement).not.toHaveClass('dark')
  })
})
