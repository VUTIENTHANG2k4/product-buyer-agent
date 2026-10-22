import { expect, test } from '@playwright/test'
import { askAgent, productNameAt } from './helpers.ts'

test.describe('Luồng 2: chọn 2 sản phẩm → so sánh', () => {
  test('nút So sánh chỉ bật khi chọn đủ 2; ngăn so sánh hiện cả hai sản phẩm và đánh dấu rẻ nhất', async ({
    page,
  }) => {
    const table = await askAgent(page)
    const first = await productNameAt(table, 0)
    const second = await productNameAt(table, 1)

    const compare = page.getByRole('button', { name: 'So sánh', exact: true })
    await expect(compare).toBeDisabled()
    await table.getByRole('checkbox', { name: `Chọn ${first} để so sánh` }).check()
    await expect(compare).toBeDisabled()
    await table.getByRole('checkbox', { name: `Chọn ${second} để so sánh` }).check()
    await expect(compare).toBeEnabled()
    await compare.click()

    const drawer = page.getByRole('dialog', { name: 'So sánh (2)' })
    await expect(drawer).toBeVisible()
    await expect(drawer.getByText(first).first()).toBeVisible()
    await expect(drawer.getByText(second).first()).toBeVisible()
    await expect(drawer.getByText('Giá thấp nhất')).toBeVisible()
    // Đúng một sản phẩm được đánh dấu rẻ nhất (dữ liệu seed không có hai giá bằng nhau).
    await expect(drawer.getByText('Rẻ nhất')).toHaveCount(1)

    // "Chỉ hiện khác biệt" không làm mất bảng.
    await drawer.getByRole('checkbox', { name: 'Chỉ hiện khác biệt' }).check()
    await expect(drawer.getByText(first).first()).toBeVisible()

    await drawer.getByRole('button', { name: 'Đóng', exact: true }).click()
    await expect(drawer).toBeHidden()
  })
})
