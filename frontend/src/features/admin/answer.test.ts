import { isValidAnswer } from './answer'

describe('isValidAnswer', () => {
  it.each(['a', 'AB12C', '  AB12C  ', 'đáp án có dấu', 'a'.repeat(200)])('%j hợp lệ', (answer) => {
    expect(isValidAnswer(answer)).toBe(true)
  })

  it.each(['', ' ', '\t\n', 'a'.repeat(201), `ab${String.fromCharCode(0)}cd`])(
    '%j không hợp lệ',
    (answer) => {
      expect(isValidAnswer(answer)).toBe(false)
    },
  )

  it('độ dài tính sau khi cắt khoảng trắng hai đầu', () => {
    expect(isValidAnswer(` ${'a'.repeat(200)} `)).toBe(true)
  })
})
