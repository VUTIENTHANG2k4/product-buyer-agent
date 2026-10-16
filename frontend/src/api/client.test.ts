import { delay, http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { ApiError, apiFetch, apiUrl } from './client'

describe('apiUrl', () => {
  it('nối gốc máy chủ, tự thêm /api và bỏ dấu / thừa', () => {
    expect(apiUrl('/health')).toBe('http://api.test/api/health')
    expect(apiUrl('products/1')).toBe('http://api.test/api/products/1')
  })

  it('bỏ dấu / ở cuối VITE_API_BASE_URL', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.test///')
    try {
      expect(apiUrl('/health')).toBe('http://api.test/api/health')
    } finally {
      vi.unstubAllEnvs()
    }
  })

  it('dùng đường dẫn tương đối /api/... khi VITE_API_BASE_URL là chuỗi rỗng (sau reverse proxy)', () => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    try {
      expect(apiUrl('/health')).toBe('/api/health')
    } finally {
      vi.unstubAllEnvs()
    }
  })

  it('dùng http://localhost:8000 khi VITE_API_BASE_URL không được đặt', () => {
    vi.stubEnv('VITE_API_BASE_URL', undefined)
    try {
      expect(apiUrl('/health')).toBe('http://localhost:8000/api/health')
    } finally {
      vi.unstubAllEnvs()
    }
  })
})

describe('apiFetch', () => {
  it('trả JSON khi thành công', async () => {
    server.use(http.get('http://api.test/api/health', () => HttpResponse.json({ status: 'ok' })))
    await expect(apiFetch<{ status: string }>('/health')).resolves.toEqual({ status: 'ok' })
  })

  it('gửi JSON trong thân yêu cầu', async () => {
    server.use(
      http.post('http://api.test/api/lists', async ({ request }) =>
        HttpResponse.json(await request.json(), { status: 201 }),
      ),
    )
    await expect(
      apiFetch('/lists', { method: 'POST', json: { name: 'Máy mới' } }),
    ).resolves.toEqual({ name: 'Máy mới' })
  })

  it('trả undefined với phản hồi 204', async () => {
    server.use(
      http.delete('http://api.test/api/lists/1', () => new HttpResponse(null, { status: 204 })),
    )
    await expect(apiFetch('/lists/1', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('chuyển lỗi 4xx thành ApiError có mã và thông điệp từ máy chủ', async () => {
    server.use(
      http.get('http://api.test/api/products/9', () =>
        HttpResponse.json(
          { error: { code: 'NOT_FOUND', message: 'Không tìm thấy sản phẩm' } },
          { status: 404 },
        ),
      ),
    )
    const error = await apiFetch('/products/9').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 404,
      code: 'NOT_FOUND',
      message: 'Không tìm thấy sản phẩm',
    })
  })

  it('dùng mã HTTP_<status> khi thân lỗi không phải JSON', async () => {
    server.use(
      http.get('http://api.test/api/boom', () => new HttpResponse('oops', { status: 500 })),
    )
    const error = await apiFetch('/boom').catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 500, code: 'HTTP_500' })
  })

  it('chuyển lỗi mạng thành ApiError NETWORK_ERROR', async () => {
    server.use(http.get('http://api.test/api/down', () => HttpResponse.error()))
    const error = await apiFetch('/down').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 0, code: 'NETWORK_ERROR' })
  })

  it('trả undefined với 200 không có thân', async () => {
    server.use(http.post('http://api.test/api/ping', () => new HttpResponse(null, { status: 200 })))
    await expect(apiFetch('/ping', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('chuyển thân 2xx không phải JSON thành ApiError INVALID_RESPONSE', async () => {
    server.use(http.get('http://api.test/api/html', () => HttpResponse.text('<html></html>')))
    const error = await apiFetch('/html').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 200, code: 'INVALID_RESPONSE' })
  })

  it('ném lại lỗi hủy (AbortError), không đổi thành NETWORK_ERROR', async () => {
    server.use(
      http.get('http://api.test/api/slow', async () => {
        await delay('infinite')
        return HttpResponse.json({})
      }),
    )
    const controller = new AbortController()
    const pending = apiFetch('/slow', { signal: controller.signal })
    controller.abort()
    const error = await pending.catch((e: unknown) => e)
    expect(error).not.toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ name: 'AbortError' })
  })
})
