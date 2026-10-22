/** Phần trăm giảm gợi ý khi đặt ngưỡng cảnh báo (docs/08 §3.6). */
export const SUGGESTED_PERCENTS: readonly number[] = [5, 10]

/** Làm tròn tới nghìn đồng cho ngưỡng dễ đọc. */
const STEP = 1000

export interface TargetSuggestion {
  percent: number
  price: number
}

/** Ngưỡng gợi ý = giá hiện tại giảm `percent`%, làm tròn tới 1.000 ₫ và luôn thấp hơn giá hiện tại. */
export function suggestTargets(currentPrice: number): TargetSuggestion[] {
  return SUGGESTED_PERCENTS.map((percent) => {
    const rounded = Math.round((currentPrice * (100 - percent)) / 100 / STEP) * STEP
    return { percent, price: Math.min(Math.max(rounded, 1), currentPrice - 1) }
  }).filter((suggestion) => suggestion.price >= 1 && currentPrice > 1)
}

/**
 * Đọc ngưỡng người dùng gõ ("27.490.000", "27490000 ₫") thành số nguyên VND.
 * Chỉ nhận chữ số và dấu phân nhóm `.`/`,`/khoảng trắng; số lẻ hoặc chữ lạ → `null`.
 */
export function parseTargetPrice(input: string): number | null {
  const trimmed = input.replace(/[\s₫đĐ]|vnd/gi, '')
  // Dấu `.`/`,` chỉ hợp lệ khi phân nhóm hàng nghìn ("27.490.000"); "27.5" là số lẻ nên bị từ chối.
  if (/[.,]/.test(trimmed) && !/^\d{1,3}([.,]\d{3})+$/.test(trimmed)) return null
  const cleaned = trimmed.replace(/[.,]/g, '')
  if (!/^\d{1,13}$/.test(cleaned)) return null
  const value = Number(cleaned)
  return value >= 1 ? value : null
}
