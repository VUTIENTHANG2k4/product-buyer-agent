import { strings } from '@/lib/strings'

export const MAX_LIST_NAME = 200

/** Kiểm tra tên danh sách; trả thông báo lỗi hoặc `null` nếu hợp lệ. */
export function validateListName(name: string): string | null {
  if (name.trim() === '') return strings.lists.nameRequired
  if (name.trim().length > MAX_LIST_NAME) return strings.lists.nameTooLong
  return null
}
