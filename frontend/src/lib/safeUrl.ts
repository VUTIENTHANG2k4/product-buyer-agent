/** Chỉ nhận liên kết http(s) và mailto; mọi scheme khác (javascript:, data:, vbscript:…) bị bỏ. */
const SAFE_URL = /^(https?:|mailto:)/i

/**
 * Lọc URL trong Markdown (docs/05: nội dung do LLM/web viết là dữ liệu, không phải lệnh).
 * So khớp theo danh sách cho phép trên chuỗi đã cắt khoảng trắng đầu/cuối, nên các dạng che mắt như
 * `JaVa\nScRiPt:` hay `&#106;avascript:` không lọt qua; đường dẫn tương đối cũng bị bỏ vì câu trả
 * lời của agent chỉ dẫn tới trang bán (URL tuyệt đối).
 */
export function safeUrl(url: string): string {
  const trimmed = url.trim()
  return SAFE_URL.test(trimmed) ? trimmed : ''
}
