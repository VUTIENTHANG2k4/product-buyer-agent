type Listener = (event: MediaQueryListEvent) => void

export interface MatchMediaControl {
  /** Đổi kết quả của mọi truy vấn và báo cho các bộ lắng nghe `change`. */
  set: (matches: boolean) => void
  restore: () => void
}

/** Thay `window.matchMedia` bằng bản điều khiển được (vd. giả lập hệ điều hành chuyển sang chế độ tối). */
export function mockMatchMedia(initial: boolean | ((query: string) => boolean)): MatchMediaControl {
  const original = window.matchMedia
  const evaluate = typeof initial === 'function' ? initial : () => initial
  let override: boolean | null = null
  const listeners = new Set<Listener>()

  window.matchMedia = (query: string): MediaQueryList => {
    const list = {
      get matches() {
        return override ?? evaluate(query)
      },
      media: query,
      onchange: null,
      addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
      removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }
    return list as unknown as MediaQueryList
  }

  return {
    set(matches) {
      override = matches
      for (const listener of listeners) listener({ matches } as MediaQueryListEvent)
    },
    restore() {
      window.matchMedia = original
    },
  }
}
