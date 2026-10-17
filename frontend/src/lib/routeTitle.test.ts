import { titleFromMatches } from './routeTitle'

describe('titleFromMatches', () => {
  it('lấy title của route khớp sâu nhất', () => {
    expect(titleFromMatches([{ handle: { title: 'Cha' } }, { handle: { title: 'Con' } }])).toBe(
      'Con',
    )
  })

  it('bỏ qua route không có handle và dùng title của route cha', () => {
    expect(titleFromMatches([{ handle: { title: 'Cha' } }, { handle: undefined }])).toBe('Cha')
  })

  it.each([
    ['danh sách rỗng', []],
    ['handle là undefined', [{ handle: undefined }]],
    ['handle là null', [{ handle: null }]],
    ['title sai kiểu', [{ handle: { title: 1 } }]],
    ['handle không có title', [{ handle: {} }]],
  ])('trả undefined khi %s', (_name, matches) => {
    expect(titleFromMatches(matches)).toBeUndefined()
  })
})
