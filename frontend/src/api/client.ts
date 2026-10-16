import { strings } from '@/lib/strings'

const DEFAULT_BASE_URL = 'http://localhost:8000'

/** Lỗi trả về từ API: `{"error": {"code": "...", "message": "..."}}` (docs/07 §2). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export interface ApiRequestInit extends Omit<RequestInit, 'body'> {
  /** Nội dung gửi đi, được mã hóa JSON. */
  json?: unknown
}

/**
 * `VITE_API_BASE_URL` là gốc máy chủ, không gồm `/api`; client tự thêm.
 * Chuỗi rỗng nghĩa là cùng origin (đường dẫn tương đối `/api/...`, dùng sau reverse proxy);
 * chỉ khi biến không được đặt mới dùng mặc định cục bộ.
 */
export function apiUrl(path: string): string {
  const base = (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL).replace(/\/+$/, '')
  return `${base}/api/${path.replace(/^\/+/, '')}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isAbortError(error: unknown): boolean {
  // So theo tên: DOMException của jsdom và của Node là hai lớp khác nhau nên instanceof không đáng tin.
  return isRecord(error) && error.name === 'AbortError'
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`
  let message: string = strings.errors.unknown
  try {
    const body: unknown = await response.json()
    if (isRecord(body) && isRecord(body.error)) {
      if (typeof body.error.code === 'string') code = body.error.code
      if (typeof body.error.message === 'string') message = body.error.message
    }
  } catch {
    // Thân phản hồi không phải JSON: giữ mã và thông điệp mặc định.
  }
  return new ApiError(response.status, code, message)
}

export async function apiFetch<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const { json, headers, ...rest } = init
  const requestHeaders = new Headers(headers)
  requestHeaders.set('Accept', 'application/json')
  let body: string | undefined
  if (json !== undefined) {
    requestHeaders.set('Content-Type', 'application/json')
    body = JSON.stringify(json)
  }

  let response: Response
  try {
    response = await fetch(apiUrl(path), { ...rest, headers: requestHeaders, body })
  } catch (error) {
    if (isAbortError(error)) throw error
    throw new ApiError(0, 'NETWORK_ERROR', strings.errors.network)
  }

  if (!response.ok) throw await toApiError(response)

  // 2xx không có thân (204, 202, 205...) → undefined; thân có nội dung phải là JSON hợp lệ.
  const text = await response.text()
  if (text === '') return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', strings.errors.unknown)
  }
}
