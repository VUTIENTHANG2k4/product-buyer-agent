import { act, renderHook } from '@testing-library/react'
import { mockMatchMedia } from '@/test/matchMedia'
import { useMediaQuery } from './useMediaQuery'

describe('useMediaQuery', () => {
  it('trả về kết quả hiện tại và cập nhật khi truy vấn đổi', () => {
    const media = mockMatchMedia(false)
    const { result } = renderHook(() => useMediaQuery('(min-width: 640px)'))
    expect(result.current).toBe(false)
    act(() => media.set(true))
    expect(result.current).toBe(true)
    act(() => media.set(false))
    expect(result.current).toBe(false)
    media.restore()
  })

  it('đánh giá theo từng truy vấn', () => {
    const media = mockMatchMedia((query) => query.includes('640'))
    const wide = renderHook(() => useMediaQuery('(min-width: 640px)'))
    const huge = renderHook(() => useMediaQuery('(min-width: 1280px)'))
    expect(wide.result.current).toBe(true)
    expect(huge.result.current).toBe(false)
    media.restore()
  })

  it('matchMedia ném lỗi thì coi là không khớp, không vỡ', () => {
    const original = window.matchMedia
    window.matchMedia = () => {
      throw new Error('không hỗ trợ')
    }
    const { result } = renderHook(() => useMediaQuery('(min-width: 640px)'))
    expect(result.current).toBe(false)
    window.matchMedia = original
  })

  it('ngừng lắng nghe khi tháo component', () => {
    const media = mockMatchMedia(false)
    const { unmount } = renderHook(() => useMediaQuery('(min-width: 640px)'))
    unmount()
    expect(() => act(() => media.set(true))).not.toThrow()
    media.restore()
  })
})
