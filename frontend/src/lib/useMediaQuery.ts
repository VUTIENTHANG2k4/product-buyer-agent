import { useCallback, useSyncExternalStore } from 'react'

/** Theo dõi một truy vấn media (vd. `(min-width: 640px)`); không có `matchMedia` thì coi là không khớp. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      let list: MediaQueryList
      try {
        list = window.matchMedia(query)
      } catch {
        return () => undefined
      }
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    [query],
  )
  const getSnapshot = useCallback(() => {
    try {
      return window.matchMedia(query).matches
    } catch {
      return false
    }
  }, [query])
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}
