import type { ItemPatch, ShoppingListDetail } from './api'

/** Tổng tiền theo giá hiện tại của từng mục (mục không còn bán không tính), cùng công thức với máy chủ. */
export function totalOf(items: ShoppingListDetail['items']): number {
  return items.reduce(
    (sum, item) => sum + (item.current_price === null ? 0 : item.quantity * item.current_price),
    0,
  )
}

/**
 * Áp một bản vá lên chi tiết danh sách trong cache (cập nhật lạc quan). Chỉ đổi những trường có mặt
 * trong `patch` (`null` ở `note`/`preferred_offer_id` là xóa giá trị); tổng tiền tính lại theo số
 * lượng mới. Giá hiện tại do đổi nơi mua ưu tiên chỉ có sau khi tải lại từ máy chủ.
 */
export function patchItemInDetail(
  detail: ShoppingListDetail,
  itemId: number,
  patch: ItemPatch,
): ShoppingListDetail {
  const items = detail.items.map((item) => {
    if (item.item_id !== itemId) return item
    return {
      ...item,
      ...(patch.quantity !== undefined && patch.quantity !== null
        ? { quantity: patch.quantity }
        : {}),
      ...(patch.note !== undefined ? { note: patch.note } : {}),
      ...(patch.preferred_offer_id !== undefined
        ? { preferred_offer_id: patch.preferred_offer_id }
        : {}),
    }
  })
  return { ...detail, items, total_price: totalOf(items) }
}

/** Bỏ một mục khỏi chi tiết danh sách trong cache; tổng tiền và số mục tính lại. */
export function removeItemFromDetail(
  detail: ShoppingListDetail,
  itemId: number,
): ShoppingListDetail {
  const items = detail.items.filter((item) => item.item_id !== itemId)
  return { ...detail, items, item_count: items.length, total_price: totalOf(items) }
}
