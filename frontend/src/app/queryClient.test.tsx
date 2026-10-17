import { useQuery } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { ApiError, apiFetch } from '@/api/client'
import { server } from '@/mocks/server'
import { Providers } from './providers'
import { createQueryClient, shouldRetry } from './queryClient'

describe('shouldRetry', () => {
  it.each([
    ['lỗi mạng (status 0)', new ApiError(0, 'NETWORK_ERROR', 'x'), 0, true],
    ['lỗi máy chủ 500', new ApiError(500, 'HTTP_500', 'x'), 0, true],
    ['lỗi máy chủ 503', new ApiError(503, 'HTTP_503', 'x'), 0, true],
    ['lỗi 500 sau khi đã retry một lần', new ApiError(500, 'HTTP_500', 'x'), 1, false],
    ['lỗi 400', new ApiError(400, 'VALIDATION_ERROR', 'x'), 0, false],
    ['lỗi 404', new ApiError(404, 'NOT_FOUND', 'x'), 0, false],
    ['lỗi 429', new ApiError(429, 'RATE_LIMITED', 'x'), 0, false],
    ['lỗi không phải ApiError', new Error('lỗi lập trình'), 0, false],
  ])('%s → retry=%s', (_name, error, failureCount, expected) => {
    expect(shouldRetry(failureCount, error)).toBe(expected)
  })
})

describe('createQueryClient', () => {
  function runQuery(path: string) {
    const client = createQueryClient()
    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: [path],
          queryFn: () => apiFetch(path),
          retryDelay: 0,
        }),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <Providers client={client}>{children}</Providers>
        ),
      },
    )
    return result
  }

  it('không retry khi API trả 404', async () => {
    let calls = 0
    server.use(
      http.get('http://api.test/api/missing', () => {
        calls += 1
        return HttpResponse.json({ error: { code: 'NOT_FOUND', message: 'x' } }, { status: 404 })
      }),
    )
    const result = runQuery('/missing')
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(calls).toBe(1)
  })

  it('retry một lần khi API trả 500', async () => {
    let calls = 0
    server.use(
      http.get('http://api.test/api/boom', () => {
        calls += 1
        return new HttpResponse('oops', { status: 500 })
      }),
    )
    const result = runQuery('/boom')
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(calls).toBe(2)
  })

  it('retry một lần khi lỗi mạng', async () => {
    let calls = 0
    server.use(
      http.get('http://api.test/api/down', () => {
        calls += 1
        return HttpResponse.error()
      }),
    )
    const result = runQuery('/down')
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(calls).toBe(2)
  })
})
