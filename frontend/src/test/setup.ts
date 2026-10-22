import '@testing-library/jest-dom/vitest'
import { server } from '@/mocks/server'

// jsdom thiếu vài API trình duyệt mà Radix UI, Recharts và hook media query cần.
// `matchMedia` mặc định "không khớp" (giao diện sáng, màn hình hẹp); test ghi đè bằng `mockMatchMedia`.
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  })
}
// Node 25 có `localStorage` toàn cục thử nghiệm che mất bản của jsdom (thiếu `clear` khi không có
// `--localstorage-file`): thay bằng bản trong bộ nhớ để test lưu/đọc giống trình duyệt.
if (typeof window.localStorage?.clear !== 'function') {
  const data = new Map<string, string>()
  const memoryStorage: Storage = {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  }
  Object.defineProperty(window, 'localStorage', { value: memoryStorage, configurable: true })
}
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.setPointerCapture ??= () => undefined
Element.prototype.releasePointerCapture ??= () => undefined
Element.prototype.scrollIntoView ??= () => undefined

// Request không có handler làm test thất bại (kể cả khi code gọi API nuốt lỗi mạng):
// test không bao giờ gọi mạng thật.
const unhandled: string[] = []

beforeAll(() =>
  server.listen({
    onUnhandledRequest(request, print) {
      unhandled.push(`${request.method} ${request.url}`)
      print.error()
    },
  }),
)
afterEach(() => {
  server.resetHandlers()
  const requests = unhandled.splice(0)
  if (requests.length > 0) {
    throw new Error(`Request chưa có MSW handler: ${requests.join(', ')}`)
  }
})
afterAll(() => server.close())
