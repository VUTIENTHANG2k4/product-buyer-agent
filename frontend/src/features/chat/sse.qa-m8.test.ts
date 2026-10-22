import { SseParser, type SseMessage } from './sse'

function parseAll(...chunks: string[]): SseMessage[] {
  const parser = new SseParser()
  return [...chunks.flatMap((chunk) => parser.push(chunk)), ...parser.end()]
}

/** Luồng thật của máy chủ (FastAPI EventSourceResponse) dùng CRLF, có ping và id bắt đầu từ 0. */
const REAL_STREAM =
  ': ping\r\n\r\n' +
  'event: plan\r\nid: 0\r\ndata: {"q":"Máy tính xách tay – Đà Nẵng 🇻🇳"}\r\n\r\n' +
  'event: tool_start\nid: 1\ndata: {"a":1}\n\n' +
  'event: tool_end\rid: 2\rdata: {"b":2}\r\r' +
  'event: final\r\nid: 3\r\ndata: {\r\ndata:   "x": "a\\u2028b"\r\ndata: }\r\n\r\n'

describe('SseParser · biên theo đặc tả (QA M8)', () => {
  it('luồng trộn CRLF, LF và CR cho cùng kết quả dù cắt ở bất kỳ vị trí nào (mọi cặp điểm cắt)', () => {
    const expected = parseAll(REAL_STREAM)
    expect(expected.map((m) => [m.event, m.id])).toEqual([
      ['plan', '0'],
      ['tool_start', '1'],
      ['tool_end', '2'],
      ['final', '3'],
    ])
    for (let i = 0; i <= REAL_STREAM.length; i += 1) {
      for (let j = i; j <= REAL_STREAM.length; j += 1) {
        const parts = [REAL_STREAM.slice(0, i), REAL_STREAM.slice(i, j), REAL_STREAM.slice(j)]
        expect(parseAll(...parts)).toEqual(expected)
      }
    }
  })

  it('JSON nhiều dòng data nối bằng \\n vẫn là JSON hợp lệ', () => {
    const last = parseAll(REAL_STREAM).at(-1)
    expect(last?.data).toBe('{\n  "x": "a\\u2028b"\n}')
    expect(JSON.parse(last?.data ?? '')).toEqual({ x: 'a b' })
  })

  it('U+2028, U+2029 và U+0085 trong dữ liệu không bị coi là xuống dòng', () => {
    const data = 'a b c\u0085d'
    expect(parseAll(`data: ${data}\n\n`)).toEqual([{ event: 'message', data, id: null }])
  })

  it('dòng "data" không có dấu hai chấm là một dòng dữ liệu rỗng', () => {
    expect(parseAll('data\n\n')).toEqual([{ event: 'message', data: '', id: null }])
    expect(parseAll('data\ndata\n\n')[0]?.data).toBe('\n')
  })

  it('"id:" rỗng đặt lại id về chuỗi rỗng cho các sự kiện sau', () => {
    const ids = parseAll('id: 5\ndata: a\n\nid:\ndata: b\n\n').map((m) => m.id)
    expect(ids).toEqual(['5', ''])
  })

  it('tên trường phân biệt hoa thường: "Data:" và "EVENT:" bị bỏ qua', () => {
    expect(parseAll('Data: x\n\n')).toEqual([])
    expect(parseAll('EVENT: plan\ndata: x\n\n')).toEqual([
      { event: 'message', data: 'x', id: null },
    ])
  })

  it('event không có data không rò tên sang sự kiện kế tiếp', () => {
    expect(parseAll('event: plan\n\ndata: x\n\n')).toEqual([
      { event: 'message', data: 'x', id: null },
    ])
  })

  it('event: rỗng quay về tên "message"', () => {
    expect(parseAll('event:\ndata: x\n\n')[0]?.event).toBe('message')
  })

  it('retry: và chú thích giữa hai dòng data không làm mất data', () => {
    const [message] = parseAll('data: 1\n: ghi chú\nretry: 3000\ndata: 2\n\n')
    expect(message?.data).toBe('1\n2')
  })

  it('luồng chỉ có ping/chú thích không phát sự kiện nào', () => {
    expect(parseAll(': ping\r\n\r\n: ping\r\n\r\n')).toEqual([])
  })

  it('nhiều dòng trống liên tiếp không sinh sự kiện rỗng', () => {
    expect(parseAll('\n\n\n\ndata: x\n\n\n\n')).toEqual([{ event: 'message', data: 'x', id: null }])
  })

  it('luồng bị cắt khi sự kiện dở (không có dòng trống) thì bỏ sự kiện đó', () => {
    expect(parseAll('event: final\nid: 9\ndata: {"a":1}\n')).toEqual([])
    expect(parseAll('event: final\nid: 9\ndata: {"a":')).toEqual([])
  })

  // BUG-M8-1: `SseParser.end()` thêm một dòng trống giả sau `\r` đang chờ, nên sự kiện dở (chưa có
  // dòng trống thật) vẫn bị phát. XPASS báo đỏ: gỡ `.fails` khi sửa.
  it('luồng đứt ngay sau một \\r của dòng data (sự kiện chưa có dòng trống) thì không phát', () => {
    // Đặc tả HTML: sự kiện chưa gặp dòng trống cuối luồng bị loại bỏ, kể cả khi dòng cuối kết thúc bằng \r.
    expect(parseAll('event: final\ndata: {"a":1}\r')).toEqual([])
  })

  it('một dòng cực dài (5 triệu ký tự) bị cắt thành nhiều mảnh vẫn ghép đủ', () => {
    const big = 'x'.repeat(5_000_000)
    const text = `data: ${big}\n\n`
    const chunks: string[] = []
    for (let i = 0; i < text.length; i += 65_536) chunks.push(text.slice(i, i + 65_536))
    const messages = parseAll(...chunks)
    expect(messages).toHaveLength(1)
    expect(messages[0]?.data.length).toBe(5_000_000)
  })
})
