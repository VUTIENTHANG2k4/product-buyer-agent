import { ApiError } from '@/api/client'
import { strings } from '@/lib/strings'

/** Thông điệp tiếng Việt từ API; lỗi lạ không bao giờ lộ stack trace hay `Error.message` tiếng Anh. */
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : strings.errors.unknown
}
