import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { ApiError, apiFetch } from './client'

const BASE = 'http://api.test/api'

/** Gọi `apiFetch` và trả về lỗi (hoặc undefined nếu không lỗi) để khẳng định trên lỗi. */
async function failure(path: string, init?: Parameters<typeof apiFetch>[1]): Promise<ApiError> {
  const error = await apiFetch(path, init).catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  return error as ApiError
}

describe('apiFetch · yêu cầu gửi đi', () => {
  it('giữ nguyên query string, kể cả ký tự đã mã hóa và tiếng Việt', async () => {
    let seen: URL | undefined
    server.use(
      http.get(`${BASE}/products`, ({ request }) => {
        seen = new URL(request.url)
        return HttpResponse.json([])
      }),
    )
    await apiFetch('/products?category=laptop&q=m%C3%A1y%20t%C3%ADnh&page=2&tag=a%26b')
    expect(seen?.pathname).toBe('/api/products')
    expect(seen?.searchParams.get('category')).toBe('laptop')
    expect(seen?.searchParams.get('q')).toBe('máy tính')
    expect(seen?.searchParams.get('page')).toBe('2')
    expect(seen?.searchParams.get('tag')).toBe('a&b')
  })

  it('luôn gửi Accept: application/json và không gửi Content-Type khi không có json', async () => {
    let headers: Headers | undefined
    server.use(
      http.get(`${BASE}/health`, ({ request }) => {
        headers = request.headers
        return HttpResponse.json({})
      }),
    )
    await apiFetch('/health')
    expect(headers?.get('accept')).toBe('application/json')
    expect(headers?.has('content-type')).toBe(false)
  })

  it('gửi Content-Type: application/json kèm thân khi có json, ghi đè Content-Type của người gọi', async () => {
    let seen: { contentType: string | null; body: string } | undefined
    server.use(
      http.post(`${BASE}/lists`, async ({ request }) => {
        seen = { contentType: request.headers.get('content-type'), body: await request.text() }
        return HttpResponse.json({})
      }),
    )
    await apiFetch('/lists', {
      method: 'POST',
      json: { name: 'Máy mới' },
      headers: { 'Content-Type': 'text/plain' },
    })
    expect(seen?.contentType).toBe('application/json')
    expect(seen?.body).toBe('{"name":"Máy mới"}')
  })

  it('giữ các header khác do người gọi đặt, dù truyền dạng object, mảng hay Headers', async () => {
    const seen: (string | null)[] = []
    server.use(
      http.get(`${BASE}/h`, ({ request }) => {
        seen.push(request.headers.get('x-request-id'))
        return HttpResponse.json({})
      }),
    )
    await apiFetch('/h', { headers: { 'X-Request-Id': 'a' } })
    await apiFetch('/h', { headers: [['X-Request-Id', 'b']] })
    await apiFetch('/h', { headers: new Headers({ 'X-Request-Id': 'c' }) })
    expect(seen).toEqual(['a', 'b', 'c'])
  })

  it.each([
    ['0', 0],
    ['false', false],
    ['chuỗi rỗng', ''],
    ['null', null],
    ['mảng rỗng', []],
  ])('vẫn gửi thân JSON khi json là giá trị "falsy" (%s)', async (_name, value) => {
    let body: unknown
    server.use(
      http.post(`${BASE}/echo`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({})
      }),
    )
    await apiFetch('/echo', { method: 'POST', json: value })
    expect(body).toEqual(value)
  })

  it('không gửi thân khi json là undefined, kể cả với POST', async () => {
    let seen: { body: string; contentType: string | null } | undefined
    server.use(
      http.post(`${BASE}/empty`, async ({ request }) => {
        seen = { body: await request.text(), contentType: request.headers.get('content-type') }
        return new HttpResponse(null, { status: 202 })
      }),
    )
    await apiFetch('/empty', { method: 'POST' })
    expect(seen).toEqual({ body: '', contentType: null })
  })

  it('mã hóa đúng tiếng Việt có dấu ở dạng tổ hợp (NFD) và dựng sẵn (NFC) mà không đổi chuỗi', async () => {
    const nfc = 'Máy tính Đà Nẵng'
    const nfd = nfc.normalize('NFD')
    expect(nfd).not.toBe(nfc)
    const bodies: string[] = []
    server.use(
      http.post(`${BASE}/echo`, async ({ request }) => {
        const body = (await request.json()) as { name: string }
        bodies.push(body.name)
        return HttpResponse.json({})
      }),
    )
    await apiFetch('/echo', { method: 'POST', json: { name: nfc } })
    await apiFetch('/echo', { method: 'POST', json: { name: nfd } })
    expect(bodies).toEqual([nfc, nfd])
  })
})

describe('apiFetch · thân phản hồi thành công', () => {
  it.each([
    ['0', '0', 0],
    ['false', 'false', false],
    ['chuỗi rỗng JSON', '""', ''],
    ['null', 'null', null],
  ])(
    'trả đúng giá trị JSON "falsy" %s (không nhầm với "không có thân")',
    async (_n, raw, expected) => {
      server.use(
        http.get(
          `${BASE}/v`,
          () => new HttpResponse(raw, { headers: { 'Content-Type': 'application/json' } }),
        ),
      )
      await expect(apiFetch('/v')).resolves.toBe(expected)
    },
  )

  it('202 có thân JSON vẫn được đọc (không bị coi là rỗng)', async () => {
    server.use(
      http.post(`${BASE}/chat`, () => HttpResponse.json({ run_id: 'r1' }, { status: 202 })),
    )
    await expect(apiFetch('/chat', { method: 'POST', json: { message: 'x' } })).resolves.toEqual({
      run_id: 'r1',
    })
  })

  it('JSON bị cắt cụt (mất kết nối giữa chừng) thành INVALID_RESPONSE chứ không ném SyntaxError', async () => {
    server.use(http.get(`${BASE}/cut`, () => new HttpResponse('{"items": [1, 2')))
    expect(await failure('/cut')).toMatchObject({ status: 200, code: 'INVALID_RESPONSE' })
  })

  it('thông điệp của INVALID_RESPONSE là tiếng Việt chung, không lộ nội dung thân', async () => {
    server.use(http.get(`${BASE}/html`, () => HttpResponse.text('<html>Traceback secret</html>')))
    const error = await failure('/html')
    expect(error.message).toBe('Đã có lỗi xảy ra. Hãy thử lại.')
    expect(error.message).not.toContain('Traceback')
  })
})

describe('apiFetch · thân lỗi dị dạng', () => {
  const unknownMessage = 'Đã có lỗi xảy ra. Hãy thử lại.'

  it.each([
    ['error là chuỗi', { error: 'boom' }],
    ['error là mảng', { error: ['a', 'b'] }],
    ['error là null', { error: null }],
    ['error là số', { error: 500 }],
    ['thân là null', null],
    ['thân là mảng', [{ error: { code: 'X' } }]],
    ['thân là chuỗi JSON', 'lỗi'],
    ['thân là số', 42],
    ['thân là đối tượng rỗng', {}],
    ['kiểu FastAPI mặc định {detail}', { detail: 'Not Found' }],
  ])('dùng mã HTTP_<status> và thông điệp mặc định khi %s', async (_name, body) => {
    server.use(http.get(`${BASE}/bad`, () => HttpResponse.json(body, { status: 503 })))
    const error = await failure('/bad')
    expect(error).toMatchObject({ status: 503, code: 'HTTP_503', message: unknownMessage })
    expect(error.details).toBeUndefined()
  })

  it.each([
    ['code là số', { error: { code: 404, message: 'm' } }, 'HTTP_404', 'm'],
    ['code là null', { error: { code: null, message: 'm' } }, 'HTTP_404', 'm'],
    ['message là số', { error: { code: 'C', message: 7 } }, 'C', unknownMessage],
    ['message là đối tượng', { error: { code: 'C', message: { vi: 'x' } } }, 'C', unknownMessage],
    ['chỉ có code', { error: { code: 'ONLY_CODE' } }, 'ONLY_CODE', unknownMessage],
    ['chỉ có message', { error: { message: 'chỉ thông điệp' } }, 'HTTP_404', 'chỉ thông điệp'],
  ])('xử lý từng trường riêng lẻ khi %s', async (_name, body, code, message) => {
    server.use(http.get(`${BASE}/bad`, () => HttpResponse.json(body, { status: 404 })))
    expect(await failure('/bad')).toMatchObject({ status: 404, code, message })
  })

  it.each([
    ['đối tượng theo trường', { name: 'Tên không được để trống' }],
    ['mảng lỗi kiểu FastAPI', [{ loc: ['body', 'name'], msg: 'field required' }]],
    ['chuỗi', 'chi tiết'],
    ['số 0', 0],
    ['false', false],
    ['null', null],
    ['đối tượng rỗng', {}],
    ['lồng nhau sâu', { a: { b: { c: [1, { d: 'đ' }] } } }],
  ])('giữ nguyên details khi là %s', async (_name, details) => {
    server.use(
      http.post(`${BASE}/lists`, () =>
        HttpResponse.json(
          { error: { code: 'VALIDATION_ERROR', message: 'm', details } },
          { status: 422 },
        ),
      ),
    )
    expect((await failure('/lists', { method: 'POST', json: {} })).details).toEqual(details)
  })

  it('đọc được thông điệp tiếng Việt có dấu tổ hợp (NFD) đúng nguyên văn', async () => {
    const message = 'Không tìm thấy sản phẩm'.normalize('NFD')
    server.use(
      http.get(`${BASE}/p`, () =>
        HttpResponse.json({ error: { code: 'PRODUCT_NOT_FOUND', message } }, { status: 404 }),
      ),
    )
    expect((await failure('/p')).message).toBe(message)
  })

  it('502 từ reverse proxy trả HTML với Content-Type JSON không làm sập, trả HTTP_502', async () => {
    server.use(
      http.get(
        `${BASE}/proxy`,
        () =>
          new HttpResponse('<html>Bad Gateway</html>', {
            status: 502,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
    expect(await failure('/proxy')).toMatchObject({
      status: 502,
      code: 'HTTP_502',
      message: unknownMessage,
    })
  })

  it('lỗi có thân rỗng (500 không nội dung) vẫn thành ApiError HTTP_500', async () => {
    server.use(http.get(`${BASE}/empty500`, () => new HttpResponse(null, { status: 500 })))
    expect(await failure('/empty500')).toMatchObject({ status: 500, code: 'HTTP_500' })
  })

  it('304 Not Modified (3xx không có thân) là lỗi HTTP_304, không phải thành công rỗng', async () => {
    server.use(http.get(`${BASE}/cached`, () => new HttpResponse(null, { status: 304 })))
    expect(await failure('/cached')).toMatchObject({ status: 304, code: 'HTTP_304' })
  })

  it('ApiError mang tên "ApiError" và là Error để công cụ báo lỗi nhận ra', async () => {
    server.use(http.get(`${BASE}/x`, () => new HttpResponse(null, { status: 418 })))
    const error = await failure('/x')
    expect(error).toBeInstanceOf(Error)
    expect(error.name).toBe('ApiError')
  })

  // Lỗi đã biết (thấp): message rỗng từ máy chủ được giữ nguyên. it.fails: hết lỗi thì test báo để gỡ.
  it.fails(
    'thông điệp lỗi từ máy chủ rỗng thì dùng thông điệp mặc định để không hiện hộp lỗi trống',
    async () => {
      server.use(
        http.get(`${BASE}/blank`, () =>
          HttpResponse.json({ error: { code: 'X', message: '' } }, { status: 400 }),
        ),
      )
      expect((await failure('/blank')).message).not.toBe('')
    },
  )
})

describe('apiFetch · hủy yêu cầu', () => {
  it('signal đã abort sẵn: ném AbortError và không gửi yêu cầu nào', async () => {
    let calls = 0
    server.use(
      http.get(`${BASE}/never`, () => {
        calls += 1
        return HttpResponse.json({})
      }),
    )
    const controller = new AbortController()
    controller.abort()
    const error = await apiFetch('/never', { signal: controller.signal }).catch((e: unknown) => e)
    expect(error).not.toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ name: 'AbortError' })
    expect(calls).toBe(0)
  })

  // Lỗi đã biết (thấp): chỉ nhận AbortError theo tên, abort(lý do khác) thành NETWORK_ERROR. it.fails như trên.
  it.fails(
    'abort kèm lý do tùy ý vẫn là hủy, không biến thành NETWORK_ERROR có thể bị retry',
    async () => {
      server.use(http.get(`${BASE}/never`, () => HttpResponse.json({})))
      const controller = new AbortController()
      controller.abort(new Error('người dùng rời trang'))
      const error = await apiFetch('/never', { signal: controller.signal }).catch((e: unknown) => e)
      expect(error).not.toBeInstanceOf(ApiError)
    },
  )

  it('signal.timeout hết hạn được coi là lỗi mạng (status 0) để lớp trên có thể thử lại', async () => {
    server.use(http.get(`${BASE}/slow`, () => HttpResponse.json({})))
    const controller = new AbortController()
    controller.abort(new DOMException('hết giờ', 'TimeoutError'))
    expect(await failure('/slow', { signal: controller.signal })).toMatchObject({
      status: 0,
      code: 'NETWORK_ERROR',
    })
  })
})
