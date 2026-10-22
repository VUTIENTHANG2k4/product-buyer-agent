export const MAX_ANSWER_LENGTH = 200

/** Đáp án hợp lệ: 1–200 ký tự (sau khi cắt khoảng trắng hai đầu) và không có ký tự NUL. */
export function isValidAnswer(answer: string): boolean {
  const trimmed = answer.trim()
  return (
    trimmed.length >= 1 &&
    trimmed.length <= MAX_ANSWER_LENGTH &&
    !trimmed.split('').some((char) => char.charCodeAt(0) === 0)
  )
}
