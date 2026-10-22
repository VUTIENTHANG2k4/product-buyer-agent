import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/** Câu hỏi mà model giả (`ShoppingFakeChatModel`) hiểu: nhóm hàng + trần giá → bảng laptop từ seed `e2e`. */
export const LAPTOP_QUESTION = 'laptop gaming dưới 30 triệu'

/** Gửi một câu từ trang chính rồi chờ tới khi bảng kết quả hiện ra ở trang hội thoại. */
export async function askAgent(page: Page, question: string = LAPTOP_QUESTION): Promise<Locator> {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Tin nhắn cho agent' }).fill(question)
  await page.getByRole('button', { name: 'Gửi' }).click()
  await expect(page).toHaveURL(/\/c\/\d+/)
  const table = page.getByRole('table', { name: 'Kết quả tìm kiếm' })
  await expect(table).toBeVisible({ timeout: 30_000 })
  return table
}

/** Tên sản phẩm ở hàng thứ `index` (0 là hàng dữ liệu đầu tiên) của bảng kết quả. */
export async function productNameAt(table: Locator, index: number): Promise<string> {
  const checkbox = table.getByRole('checkbox').nth(index)
  const label = (await checkbox.getAttribute('aria-label')) ?? ''
  const match = /^Chọn (.+) để so sánh$/.exec(label)
  if (!match?.[1]) throw new Error(`Không đọc được tên sản phẩm từ nhãn "${label}"`)
  return match[1]
}

/** Mở menu thao tác (⋯) của một hàng rồi chọn mục theo tên. */
export async function chooseRowAction(page: Page, productName: string, action: string) {
  await page.getByRole('button', { name: `Thao tác với ${productName}` }).click()
  await page.getByRole('menuitem', { name: action }).click()
}

/** Gốc API của backend E2E (cùng cổng với `playwright.config.ts`). */
const API_URL = 'http://localhost:8010/api'

/**
 * Xóa mọi cảnh báo qua API trước mỗi test cần tạo cảnh báo: nếu Playwright chạy lại (retry) một test
 * đã tạo cảnh báo trước khi lỗi thì lần chạy lại không bị 409 `DUPLICATE_ALERT` che mất lỗi thật.
 */
export async function clearAlerts(request: APIRequestContext): Promise<void> {
  const response = await request.get(`${API_URL}/alerts`)
  expect(response.ok()).toBeTruthy()
  const { items } = (await response.json()) as { items: { alert_id: number }[] }
  for (const alert of items) {
    const deleted = await request.delete(`${API_URL}/alerts/${alert.alert_id}`)
    expect(deleted.ok()).toBeTruthy()
  }
}

/** Tên duy nhất cho mỗi lần chạy, để spec không đụng dữ liệu của spec khác trong cùng DB. */
export const uniqueName = (prefix: string) => `${prefix} ${Date.now().toString(36)}`
