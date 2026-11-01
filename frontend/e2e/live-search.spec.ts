import { expect, test } from '@playwright/test'

/** Nhãn của bảng tìm trực tiếp tầng 2 (docs/08 §3.2); cũng là tên truy cập của bảng. */
const LIVE_LABEL = 'Tìm trực tiếp – chưa chuẩn hóa thông số'

test.describe('Luồng tầng 2: tìm trực tiếp nhóm sản phẩm khác', () => {
  test('hỏi loa bluetooth dưới 1 triệu: bảng chưa chuẩn hóa với giá và link từ mock-shop', async ({
    page,
  }) => {
    await page.goto('/')
    await page
      .getByRole('textbox', { name: 'Tin nhắn cho agent' })
      .fill('loa bluetooth dưới 1 triệu')
    await page.getByRole('button', { name: 'Gửi' }).click()
    await expect(page).toHaveURL(/\/c\/\d+/)

    const table = page.getByRole('table', { name: LIVE_LABEL })
    await expect(table).toBeVisible({ timeout: 30_000 })

    // Mock-shop có 5 loa bluetooth; chỉ 2 chiếc có giá ≤ 1 triệu (một chiếc "Liên hệ" bị bỏ khi lọc giá).
    await expect(table.getByRole('row')).toHaveCount(3) // 1 hàng tiêu đề + 2 kết quả
    await expect(
      table.getByRole('cell', { name: 'Loa Bluetooth Edifier Mock Mini M1', exact: true }),
    ).toBeVisible()
    await expect(
      table.getByRole('cell', { name: 'Loa Bluetooth Sony Mock Boom B3', exact: true }),
    ).toBeVisible()
    await expect(table.getByText('590.000 ₫')).toBeVisible()
    await expect(table.getByText('890.000 ₫')).toBeVisible()
    await expect(table.getByText('Loa Bluetooth JBL Mock Flip F2')).toHaveCount(0)

    // Link dẫn về trang nguồn (trang chi tiết của mock-shop), mở ở tab mới.
    const link = table.getByRole('link', { name: /Loa Bluetooth Sony Mock Boom B3/ })
    await expect(link).toHaveAttribute('href', /\/p\/sony-mock-boom-b3-mk-lo002$/)
    await expect(link).toHaveAttribute('target', '_blank')
  })

  test('câu tầng 2 không dựng bảng sản phẩm đã chuẩn hóa của tầng 1', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('textbox', { name: 'Tin nhắn cho agent' }).fill('ổ cứng SSD 1TB')
    await page.getByRole('button', { name: 'Gửi' }).click()
    await expect(page).toHaveURL(/\/c\/\d+/)

    await expect(page.getByRole('table', { name: LIVE_LABEL })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('table', { name: 'Kết quả tìm kiếm' })).toHaveCount(0)
  })
})
