import '@testing-library/jest-dom/vitest'
import { server } from '@/mocks/server'

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
