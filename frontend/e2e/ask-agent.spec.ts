import { expect, test } from '@playwright/test'
import { askAgent, productNameAt } from './helpers.ts'

test.describe('Luồng 1: hỏi agent → kế hoạch → bảng kết quả', () => {
  test('hỏi laptop gaming: thấy kế hoạch, các bước và bảng sản phẩm từ DB', async ({ page }) => {
    const table = await askAgent(page)

    // Câu của người dùng và kế hoạch của agent hiện trong hội thoại.
    await expect(page.getByText('laptop gaming dưới 30 triệu').first()).toBeVisible()
    await expect(page.getByText('Kế hoạch').first()).toBeVisible()

    // Bảng dựng từ DB: có ít nhất một sản phẩm hư cấu ("Mock"), giá VND, nguồn dữ liệu.
    const rows = table.getByRole('row')
    expect(await rows.count()).toBeGreaterThan(1)
    expect(await productNameAt(table, 0)).toContain('Mock')
    await expect(table.getByText(/\d{1,3}(\.\d{3})+ ₫/).first()).toBeVisible()
  })

  test('mọi sản phẩm trong bảng đều có giá không vượt trần 30 triệu', async ({ page }) => {
    const table = await askAgent(page)
    const prices = await table.locator('tbody tr').evaluateAll((trs) =>
      trs.map((tr) => {
        const match = /(\d{1,3}(?:\.\d{3})+) ₫/.exec(tr.textContent ?? '')
        return match?.[1] ? Number(match[1].replaceAll('.', '')) : null
      }),
    )
    expect(prices.length).toBeGreaterThan(0)
    for (const price of prices) {
      expect(price).not.toBeNull()
      expect(price).toBeLessThanOrEqual(30_000_000)
    }
  })

  test('câu quá chung chung: agent hỏi lại thay vì đưa bảng', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('textbox', { name: 'Tin nhắn cho agent' }).fill('xin chào')
    await page.getByRole('button', { name: 'Gửi' }).click()
    await expect(page).toHaveURL(/\/c\/\d+/)
    await expect(page.getByText('Bạn muốn tìm loại sản phẩm nào')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('table', { name: 'Kết quả tìm kiếm' })).toHaveCount(0)
  })
})
