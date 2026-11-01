/** `payload.product_ids` của tin nhắn trợ lý đã lưu; dữ liệu lạ hoặc rỗng → không có bảng. */
export function productIdsOf(payload: Record<string, unknown> | null | undefined): number[] {
  const ids = payload?.product_ids
  if (!Array.isArray(ids)) return []
  return ids.filter((id): id is number => Number.isInteger(id))
}
