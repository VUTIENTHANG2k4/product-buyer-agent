import { expect, test } from '@playwright/test'
import { askAgent, productNameAt } from './helpers.ts'

const PHONE_QUESTION = 'điện thoại samsung dưới 10 triệu'

test.describe('Điện thoại (X1): hỏi agent → bảng kết quả điện thoại từ DB', () => {
  test('hỏi điện thoại: bảng gồm máy hư cấu có thông số điện thoại và giá VND', async ({
    page,
  }) => {
    const table = await askAgent(page, PHONE_QUESTION)

    await expect(page.getByText(PHONE_QUESTION).first()).toBeVisible()
    const count = await table.getByRole('checkbox').count()
    expect(count).toBeGreaterThan(0)
    expect(await productNameAt(table, 0)).toContain('Mock')
    // Thông số chính của điện thoại (dung lượng RAM / bộ nhớ trong), không phải của laptop.
    await expect(table.getByText(/\d+ GB/).first()).toBeVisible()
    await expect(table.getByText('GPU')).toHaveCount(0)
    await expect(table.getByText(/\d{1,3}(\.\d{3})+ ₫/).first()).toBeVisible()
  })

  test('mọi điện thoại trong bảng đều có giá không vượt trần 10 triệu', async ({ page }) => {
    const table = await askAgent(page, PHONE_QUESTION)
    const prices = await table.locator('tbody tr').evaluateAll((trs) =>
      trs.map((tr) => {
        const match = /(\d{1,3}(?:\.\d{3})+) ₫/.exec(tr.textContent ?? '')
        return match?.[1] ? Number(match[1].replaceAll('.', '')) : null
      }),
    )
    expect(prices.length).toBeGreaterThan(0)
    for (const price of prices) {
      expect(price).not.toBeNull()
      expect(price).toBeLessThanOrEqual(10_000_000)
    }
  })
})
