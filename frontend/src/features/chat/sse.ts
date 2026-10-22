const NUL = String.fromCharCode(0)

/** Một sự kiện Server-Sent Events đã ghép đủ trường (`event:`, `data:`, `id:`). */
export interface SseMessage {
  event: string
  data: string
  id: string | null
}

/**
 * Bộ phân tích luồng SSE thuần (không phụ thuộc trình duyệt) theo đặc tả HTML:
 * dòng kết thúc bằng `\n`, `\r\n` hoặc `\r`; dòng trống chốt một sự kiện; dòng bắt đầu bằng `:`
 * là chú thích; nhiều dòng `data:` nối bằng `\n`. Dữ liệu có thể đến cắt ở bất kỳ vị trí nào, kể
 * cả giữa `\r\n`: phần dòng chưa xong được giữ lại cho lần `push` sau.
 */
export class SseParser {
  private pending = ''
  private event = ''
  private data: string[] = []
  private id: string | null = null
  private sawData = false

  push(chunk: string): SseMessage[] {
    const messages: SseMessage[] = []
    let text = this.pending + chunk
    this.pending = ''
    // `\r` cuối chuỗi có thể là nửa đầu của `\r\n`: chờ ký tự kế tiếp rồi mới quyết định.
    if (text.endsWith('\r')) {
      this.pending = '\r'
      text = text.slice(0, -1)
    }
    const lines = text.split(/\r\n|\n|\r/)
    this.pending = lines.pop()! + this.pending
    for (const line of lines) {
      const message = this.line(line)
      if (message) messages.push(message)
    }
    return messages
  }

  /**
   * Hết luồng: một `\r` đang chờ giờ chắc chắn là dấu xuống dòng. Dòng dở không có dấu xuống dòng
   * bị bỏ theo đặc tả.
   */
  end(): SseMessage[] {
    const text = this.pending
    this.pending = ''
    if (!text.endsWith('\r')) return []
    // Chỉ chốt dòng đang chờ; sự kiện chưa gặp dòng trống thật bị bỏ theo đặc tả (luồng đứt giữa chừng).
    const message = this.line(text.slice(0, -1))
    return message ? [message] : []
  }

  private line(line: string): SseMessage | null {
    if (line === '') {
      const message = this.sawData
        ? { event: this.event || 'message', data: this.data.join('\n'), id: this.id }
        : null
      this.event = ''
      this.data = []
      this.sawData = false
      return message
    }
    if (line.startsWith(':')) return null
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.event = value
    else if (field === 'data') {
      this.data.push(value)
      this.sawData = true
    } else if (field === 'id' && !value.includes(NUL)) this.id = value
    return null
  }
}
