import { expect, test } from '@playwright/test'
import { askAgent, chooseRowAction, productNameAt, uniqueName } from './helpers.ts'

test.describe('Luồng 3: thêm sản phẩm vào danh sách mua', () => {
  test('tạo danh sách mới từ hộp thoại rồi thấy sản phẩm, số lượng và tổng tiền ở /lists', async ({
    page,
  }) => {
    const table = await askAgent(page)
    const product = await productNameAt(table, 0)
    const listName = uniqueName('Danh sách E2E')

    await chooseRowAction(page, product, 'Thêm vào danh sách')
    const dialog = page.getByRole('dialog', { name: 'Thêm vào danh sách mua' })
    await dialog
      .getByLabel('Danh sách', { exact: true })
      .selectOption({ label: 'Tạo danh sách mới' })
    await dialog.getByLabel('Tên danh sách mới').fill(listName)
    await dialog.getByRole('button', { name: 'Thêm', exact: true }).click()
    await expect(dialog.getByText(`Đã thêm vào danh sách "${listName}".`)).toBeVisible()

    await dialog.getByRole('link', { name: 'Xem danh sách' }).click()
    await expect(page).toHaveURL(/\/lists\/\d+/)
    await expect(page.getByRole('heading', { level: 2, name: listName })).toBeVisible()
    await expect(page.getByRole('link', { name: product })).toBeVisible()
    await expect(page.getByLabel(`Số lượng của ${product}`)).toHaveValue('1')
    await expect(page.getByText('Tổng tiền theo giá hiện tại')).toBeVisible()
  })

  test('danh sách có sẵn: thêm lần nữa cùng sản phẩm thì tăng số lượng, không nhân đôi mục', async ({
    page,
  }) => {
    const table = await askAgent(page)
    const product = await productNameAt(table, 1)
    const listName = uniqueName('Danh sách trùng')

    for (const round of [1, 2]) {
      await chooseRowAction(page, product, 'Thêm vào danh sách')
      const dialog = page.getByRole('dialog', { name: 'Thêm vào danh sách mua' })
      if (round === 1) {
        await dialog
          .getByLabel('Danh sách', { exact: true })
          .selectOption({ label: 'Tạo danh sách mới' })
        await dialog.getByLabel('Tên danh sách mới').fill(listName)
      } else {
        await dialog.getByLabel('Danh sách', { exact: true }).selectOption({ label: listName })
      }
      await dialog.getByRole('button', { name: 'Thêm', exact: true }).click()
      await expect(dialog.getByText(`Đã thêm vào danh sách "${listName}".`)).toBeVisible()
      await dialog.getByRole('button', { name: 'Đóng' }).first().click()
      await expect(dialog).toBeHidden()
    }

    await page.getByRole('link', { name: 'Danh sách mua' }).click()
    await page.getByRole('link', { name: new RegExp(listName) }).click()
    await expect(page.getByRole('link', { name: product })).toHaveCount(1)
    await expect(page.getByLabel(`Số lượng của ${product}`)).toHaveValue('2')
  })
})
