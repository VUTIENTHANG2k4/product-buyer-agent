import { strings } from './strings'
import { titleFromMatches } from './routeTitle'

describe('titleFromMatches · biên', () => {
  it('không đổi thứ tự hay sửa đổi mảng đầu vào', () => {
    const matches = [{ handle: { title: 'Cha' } }, { handle: { title: 'Con' } }]
    const snapshot = structuredClone(matches)
    titleFromMatches(matches)
    expect(matches).toEqual(snapshot)
  })

  it('bỏ qua handle sai kiểu ở route con và rơi về title hợp lệ gần nhất phía trên', () => {
    expect(
      titleFromMatches([
        { handle: { title: 'Ông' } },
        { handle: { title: 'Cha' } },
        { handle: { title: 42 } },
        { handle: 'chuỗi' },
        { handle: null },
      ]),
    ).toBe('Cha')
  })

  it.each([
    ['mảng', []],
    ['hàm', () => 'x'],
    ['chuỗi', 'Tiêu đề'],
    ['số', 7],
    ['true', true],
  ])('không coi handle là %s như một RouteHandle', (_name, handle) => {
    expect(titleFromMatches([{ handle }])).toBeUndefined()
  })

  it('title tiếng Việt tổ hợp (NFD) được trả về nguyên văn, không chuẩn hóa ngầm', () => {
    const nfd = 'Danh sách mua'.normalize('NFD')
    expect(titleFromMatches([{ handle: { title: nfd } }])).toBe(nfd)
  })

  it('title rỗng của route con che title của route cha (tiêu đề trống sẽ rơi về tên ứng dụng)', () => {
    const title = titleFromMatches([{ handle: { title: 'Cha' } }, { handle: { title: '' } }])
    expect(title).toBe('')
    expect(strings.documentTitle(title)).toBe('Buyer Agent')
  })
})

describe('strings.documentTitle · biên', () => {
  it.each([
    [undefined, 'Buyer Agent'],
    ['', 'Buyer Agent'],
    ['Cảnh báo giá', 'Cảnh báo giá · Buyer Agent'],
    ['<b>x</b> & "y"', '<b>x</b> & "y" · Buyer Agent'],
    ['Đ'.repeat(500), `${'Đ'.repeat(500)} · Buyer Agent`],
  ])('documentTitle(%j)', (input, expected) => {
    expect(strings.documentTitle(input)).toBe(expected)
  })

  it('idSuffix không in gì khi không có mã và in nguyên văn mã khi có', () => {
    expect(strings.idSuffix(undefined)).toBe('')
    expect(strings.idSuffix('')).toBe('')
    expect(strings.idSuffix('7')).toBe(' (mã: 7)')
  })
})
