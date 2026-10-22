import { SseParser, type SseMessage } from './sse'

function parseAll(...chunks: string[]): SseMessage[] {
  const parser = new SseParser()
  return [...chunks.flatMap((chunk) => parser.push(chunk)), ...parser.end()]
}

describe('SseParser', () => {
  it('đọc một sự kiện đủ event, id và data', () => {
    expect(parseAll('event: plan\nid: 0\ndata: {"a":1}\n\n')).toEqual([
      { event: 'plan', data: '{"a":1}', id: '0' },
    ])
  })

  it('không có dòng event thì tên là "message"', () => {
    expect(parseAll('data: xin chào\n\n')).toEqual([
      { event: 'message', data: 'xin chào', id: null },
    ])
  })

  it('nối nhiều dòng data bằng xuống dòng', () => {
    expect(parseAll('data: một\ndata: hai\ndata:\ndata: ba\n\n')[0]?.data).toBe('một\nhai\n\nba')
  })

  it('chấp nhận cả \\r\\n và \\r làm dấu xuống dòng', () => {
    const crlf = parseAll('event: a\r\ndata: 1\r\n\r\nevent: b\r\ndata: 2\r\n\r\n')
    expect(crlf.map((m) => [m.event, m.data])).toEqual([
      ['a', '1'],
      ['b', '2'],
    ])
    expect(parseAll('event: c\rdata: 3\r\r').map((m) => [m.event, m.data])).toEqual([['c', '3']])
  })

  it('bỏ chú thích (dòng bắt đầu bằng ":") và trường lạ, không chốt sự kiện rỗng', () => {
    expect(parseAll(': keep-alive\n\nretry: 100\nfoo: bar\n\n')).toEqual([])
    expect(parseAll(': ping\nevent: x\ndata: 1\n\n')).toEqual([{ event: 'x', data: '1', id: null }])
  })

  it('chỉ bỏ đúng một dấu cách sau dấu hai chấm', () => {
    expect(parseAll('data:  hai cách\n\n')[0]?.data).toBe(' hai cách')
    expect(parseAll('data:không cách\n\n')[0]?.data).toBe('không cách')
  })

  it.each([1, 2, 3, 5, 7])('ghép đúng khi luồng bị cắt từng %d ký tự', (size) => {
    const text =
      'event: plan\nid: 3\ndata: {"x":"Đà Nẵng"}\n\nevent: final\r\nid: 4\r\ndata: 2\r\n\r\n'
    const chunks = text.match(new RegExp(`[\\s\\S]{1,${size}}`, 'gu')) ?? []
    expect(parseAll(...chunks)).toEqual([
      { event: 'plan', data: '{"x":"Đà Nẵng"}', id: '3' },
      { event: 'final', data: '2', id: '4' },
    ])
  })

  it('\\r\\n bị cắt đôi giữa hai lần đọc không tạo thêm dòng trống', () => {
    const messages = parseAll('event: a\r', '\ndata: 1\r', '\n\r', '\n')
    expect(messages).toEqual([{ event: 'a', data: '1', id: null }])
  })

  it('sự kiện chưa có dòng trống kết thúc thì chưa phát, có thì phát ở lần sau', () => {
    const parser = new SseParser()
    expect(parser.push('event: a\ndata: 1\n')).toEqual([])
    expect(parser.push('\n')).toEqual([{ event: 'a', data: '1', id: null }])
  })

  it('id giữ lại cho các sự kiện sau cho tới khi có id mới (theo đặc tả)', () => {
    const messages = parseAll('id: 1\ndata: a\n\ndata: b\n\nid: 2\ndata: c\n\n')
    expect(messages.map((m) => m.id)).toEqual(['1', '1', '2'])
  })

  it('id chứa ký tự NUL bị bỏ qua', () => {
    expect(parseAll('id: a' + String.fromCharCode(0) + 'b\ndata: x\n\n')[0]?.id).toBeNull()
  })

  it('chịu được dòng rất dài và nhiều sự kiện liên tiếp', () => {
    const big = 'x'.repeat(200_000)
    const messages = parseAll(`data: ${big}\n\n`.repeat(3))
    expect(messages).toHaveLength(3)
    expect(messages[0]?.data).toHaveLength(200_000)
  })
})
