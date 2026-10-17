import { useMutation, useQuery } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { ApiError, apiFetch } from '@/api/client'
import { server } from '@/mocks/server'
import { Providers } from './providers'
import { createQueryClient, shouldRetry } from './queryClient'

describe('shouldRetry · giá trị biên', () => {
  it.each([
    [-1, false],
    [Number.NaN, false],
    [1, false],
    [100, false],
    [399, false],
    [499, false],
    [500, true],
    [599, true],
    [600, true],
    [Number.POSITIVE_INFINITY, true],
    [Number.NEGATIVE_INFINITY, false],
  ])('ApiError status %s → retry=%s ở lần lỗi đầu', (status, expected) => {
    expect(shouldRetry(0, new ApiError(status, 'X', 'x'))).toBe(expected)
  })

  it.each([1, 2, 3, 100, Number.MAX_SAFE_INTEGER, Number.POSITIVE_INFINITY])(
    'không bao giờ retry khi failureCount = %s, kể cả lỗi mạng và 503',
    (failureCount) => {
      expect(shouldRetry(failureCount, new ApiError(0, 'NETWORK_ERROR', 'x'))).toBe(false)
      expect(shouldRetry(failureCount, new ApiError(503, 'HTTP_503', 'x'))).toBe(false)
    },
  )

  it.each([
    ['undefined', undefined],
    ['null', null],
    ['chuỗi', 'ApiError'],
    ['đối tượng có hình dạng giống ApiError', { status: 500, code: 'X', message: 'x' }],
    ['AbortError', new DOMException('hủy', 'AbortError')],
    ['TypeError', new TypeError('x is undefined')],
  ])('không retry khi lỗi là %s (không phải ApiError thật)', (_name, error) => {
    expect(shouldRetry(0, error)).toBe(false)
  })

  it('retry lớp con của ApiError như ApiError', () => {
    class Special extends ApiError {}
    expect(shouldRetry(0, new Special(502, 'HTTP_502', 'x'))).toBe(true)
  })
})

describe('createQueryClient · cấu hình mặc định', () => {
  it('đặt dữ liệu tươi 30 giây, không tự tải lại khi quay lại cửa sổ, retry dùng shouldRetry', () => {
    const options = createQueryClient().getDefaultOptions().queries
    expect(options?.staleTime).toBe(30_000)
    expect(options?.refetchOnWindowFocus).toBe(false)
    expect(options?.retry).toBe(shouldRetry)
  })

  it('không tự retry mutation (tránh gửi trùng thao tác ghi như tạo danh sách, đặt cảnh báo)', () => {
    expect(createQueryClient().getDefaultOptions().mutations?.retry).toBeUndefined()
  })

  it('mỗi lần gọi trả về client độc lập, không dùng chung bộ nhớ đệm', () => {
    const a = createQueryClient()
    const b = createQueryClient()
    a.setQueryData(['k'], 1)
    expect(a).not.toBe(b)
    expect(b.getQueryData(['k'])).toBeUndefined()
  })
})

describe('createQueryClient · hành vi retry thực tế', () => {
  function wrapperFor(client = createQueryClient()) {
    return ({ children }: { children: ReactNode }) => (
      <Providers client={client}>{children}</Providers>
    )
  }

  it('lần retry thành công thì query có dữ liệu và không báo lỗi', async () => {
    let calls = 0
    server.use(
      http.get('http://api.test/api/flaky', () => {
        calls += 1
        return calls === 1
          ? new HttpResponse(null, { status: 503 })
          : HttpResponse.json({ ok: true })
      }),
    )
    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['flaky'],
          queryFn: () => apiFetch<{ ok: boolean }>('/flaky'),
          retryDelay: 0,
        }),
      { wrapper: wrapperFor() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({ ok: true })
    expect(result.current.isError).toBe(false)
    expect(calls).toBe(2)
  })

  it.each([400, 401, 403, 404, 409, 422, 429])('không retry khi API trả %s', async (status) => {
    let calls = 0
    server.use(
      http.get('http://api.test/api/client-error', () => {
        calls += 1
        return new HttpResponse(null, { status })
      }),
    )
    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['client-error', status],
          queryFn: () => apiFetch('/client-error'),
          retryDelay: 0,
        }),
      { wrapper: wrapperFor() },
    )
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toMatchObject({ status })
    expect(calls).toBe(1)
  })

  it('mutation gặp lỗi 500 chỉ gửi đúng một lần', async () => {
    let calls = 0
    server.use(
      http.post('http://api.test/api/lists', () => {
        calls += 1
        return new HttpResponse(null, { status: 500 })
      }),
    )
    const { result } = renderHook(
      () =>
        useMutation({
          mutationFn: (name: string) => apiFetch('/lists', { method: 'POST', json: { name } }),
        }),
      { wrapper: wrapperFor() },
    )
    result.current.mutate('Máy mới')
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(calls).toBe(1)
  })

  it('mutation gặp lỗi mạng chỉ gửi đúng một lần', async () => {
    let calls = 0
    server.use(
      http.post('http://api.test/api/lists', () => {
        calls += 1
        return HttpResponse.error()
      }),
    )
    const { result } = renderHook(
      () =>
        useMutation({
          mutationFn: () => apiFetch('/lists', { method: 'POST', json: {} }),
        }),
      { wrapper: wrapperFor() },
    )
    result.current.mutate()
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(calls).toBe(1)
    expect(result.current.error).toMatchObject({ code: 'NETWORK_ERROR' })
  })
})
