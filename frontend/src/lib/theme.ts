import { useCallback, useEffect, useState } from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'

/** Khóa `localStorage`; script trong `index.html` đọc cùng khóa để không nháy sáng/tối khi tải trang. */
export const THEME_STORAGE_KEY = 'buyer-agent-theme'

const MODES: readonly ThemeMode[] = ['light', 'dark', 'system']
const DARK_QUERY = '(prefers-color-scheme: dark)'

function isThemeMode(value: unknown): value is ThemeMode {
  return MODES.includes(value as ThemeMode)
}

/** Giá trị đã lưu; `localStorage` có thể ném lỗi (cửa sổ riêng tư, bị chặn) → mặc định theo hệ thống. */
export function readStoredTheme(): ThemeMode {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isThemeMode(value) ? value : 'system'
  } catch {
    return 'system'
  }
}

function storeTheme(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // Không lưu được thì đổi theme vẫn có hiệu lực trong phiên này.
  }
}

export function systemPrefersDark(): boolean {
  try {
    return window.matchMedia(DARK_QUERY).matches
  } catch {
    return false
  }
}

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): 'light' | 'dark' {
  if (mode === 'system') return prefersDark ? 'dark' : 'light'
  return mode
}

/** Đặt lớp `dark` trên `<html>` (token ở `globals.css` đổi theo lớp này). */
export function applyTheme(mode: ThemeMode): void {
  const dark = resolveTheme(mode, systemPrefersDark()) === 'dark'
  document.documentElement.classList.toggle('dark', dark)
}

/** Chế độ giao diện hiện tại + hàm đổi; ở chế độ "theo hệ thống" tự đổi khi hệ điều hành đổi. */
export function useTheme(): { mode: ThemeMode; setMode: (mode: ThemeMode) => void } {
  const [mode, setModeState] = useState<ThemeMode>(readStoredTheme)

  useEffect(() => {
    applyTheme(mode)
    if (mode !== 'system') return
    let query: MediaQueryList
    try {
      query = window.matchMedia(DARK_QUERY)
    } catch {
      return
    }
    const onChange = () => applyTheme('system')
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [mode])

  const setMode = useCallback((next: ThemeMode) => {
    storeTheme(next)
    setModeState(next)
  }, [])

  return { mode, setMode }
}
