import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'

const MAX_RETRIES = 1

/**
 * Chỉ thử lại lỗi tạm thời: mất kết nối (status 0) hoặc máy chủ lỗi (>= 500).
 * Lỗi 4xx là lỗi của yêu cầu nên thử lại cũng không đổi kết quả.
 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES) return false
  return error instanceof ApiError && (error.status === 0 || error.status >= 500)
}

export const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: shouldRetry, refetchOnWindowFocus: false },
    },
  })
