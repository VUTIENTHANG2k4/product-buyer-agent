/**
 * Độ dài theo điểm mã Unicode (một emoji là 1), khớp cách Pydantic đếm `max_length` ở backend;
 * `String.length` đếm đơn vị UTF-16 nên emoji tính thành 2 và chặn oan người dùng.
 */
export function codePointLength(text: string): number {
  return Array.from(text).length
}
