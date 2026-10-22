import { expect, test } from '@playwright/test'
import { askAgent, chooseRowAction, clearAlerts, productNameAt } from './helpers.ts'

test.describe('Luồng 4: đặt cảnh báo giảm giá', () => {
  test.beforeEach(async ({ request }) => {
    await clearAlerts(request)
  })

  test('chọn ngưỡng gợi ý −5%, tạo cảnh báo rồi thấy nó ở /alerts với trạng thái đang theo dõi', async ({
    page,
  }) => {
    const table = await askAgent(page)
    const product = await productNameAt(table, 2)

    await chooseRowAction(page, product, 'Báo khi giảm giá')
    const dialog = page.getByRole('dialog', { name: 'Báo khi giảm giá' })
    await expect(dialog.getByText(/Giá thấp nhất hiện tại: /)).toBeVisible()
    await dialog.getByRole('button', { name: /^−5%/ }).click()
    await dialog.getByLabel('Kênh nhận thông báo').selectOption({ label: 'Email' })
    await dialog.getByLabel('Nơi nhận (tùy chọn)').fill('e2e@example.com')
    await dialog.getByRole('button', { name: 'Tạo cảnh báo' }).click()
    await expect(dialog.getByText('Đã tạo cảnh báo giá.')).toBeVisible()

    await dialog.getByRole('link', { name: 'Xem cảnh báo' }).click()
    await expect(page).toHaveURL(/\/alerts$/)
    const row = page.getByRole('row').filter({ has: page.getByRole('link', { name: product }) })
    await expect(row).toBeVisible()
    await expect(row.getByText('Đang theo dõi')).toBeVisible()
    await expect(row.getByText('e2e@example.com')).toBeVisible()

    // "Gửi thử" luôn trả lý do vì bộ gửi thuộc M9: giao diện không được nói là đã gửi.
    await row.getByRole('button', { name: `Gửi thử: ${product}` }).click()
    await expect(row.getByText(/^Chưa gửi được thông báo thử/)).toBeVisible()
  })

  test('đặt lại cùng ngưỡng cho cùng sản phẩm: báo trùng, không tạo thêm cảnh báo', async ({
    page,
  }) => {
    const table = await askAgent(page)
    const product = await productNameAt(table, 3)

    for (const round of [1, 2]) {
      await chooseRowAction(page, product, 'Báo khi giảm giá')
      const dialog = page.getByRole('dialog', { name: 'Báo khi giảm giá' })
      await dialog.getByRole('button', { name: /^−10%/ }).click()
      await dialog.getByLabel('Nơi nhận (tùy chọn)').fill('e2e@example.com')
      await dialog.getByRole('button', { name: 'Tạo cảnh báo' }).click()
      if (round === 1) {
        await expect(dialog.getByText('Đã tạo cảnh báo giá.')).toBeVisible()
        await dialog.getByRole('button', { name: 'Đóng' }).first().click()
        await expect(dialog).toBeHidden()
      } else {
        await expect(dialog.getByRole('alert')).toBeVisible()
        await expect(dialog.getByText('Đã tạo cảnh báo giá.')).toHaveCount(0)
      }
    }
  })
})
