import { listDetail, listItem } from '@/mocks/data'
import { patchItemInDetail, removeItemFromDetail, totalOf } from './optimistic'

const a = listItem({ item_id: 1, quantity: 2, current_price: 10_000_000 })
const b = listItem({ item_id: 2, quantity: 1, current_price: 5_000_000 })
const gone = listItem({ item_id: 3, quantity: 4, current_price: null })

describe('totalOf', () => {
  it('cộng số lượng × giá hiện tại, bỏ mục không còn bán', () => {
    expect(totalOf([a, b, gone])).toBe(25_000_000)
    expect(totalOf([])).toBe(0)
    expect(totalOf([gone])).toBe(0)
  })
})

describe('patchItemInDetail', () => {
  const detail = listDetail({ items: [a, b, gone] })

  it('đổi số lượng và tính lại tổng tiền, không đụng mục khác', () => {
    const next = patchItemInDetail(detail, 1, { quantity: 3 })
    expect(next.items[0]?.quantity).toBe(3)
    expect(next.items[1]).toBe(b)
    expect(next.total_price).toBe(35_000_000)
  })

  it('đổi ghi chú; null xóa ghi chú', () => {
    const withNote = patchItemInDetail(detail, 2, { note: 'màu đen' })
    expect(withNote.items[1]?.note).toBe('màu đen')
    expect(patchItemInDetail(withNote, 2, { note: null }).items[1]?.note).toBeNull()
  })

  it('đổi nơi mua ưu tiên; null trả về mặc định', () => {
    const next = patchItemInDetail(detail, 1, { preferred_offer_id: 77 })
    expect(next.items[0]?.preferred_offer_id).toBe(77)
    expect(
      patchItemInDetail(next, 1, { preferred_offer_id: null }).items[0]?.preferred_offer_id,
    ).toBeNull()
  })

  it('trường vắng giữ nguyên (khác với null)', () => {
    const noted = patchItemInDetail(detail, 1, { note: 'x', preferred_offer_id: 5 })
    const next = patchItemInDetail(noted, 1, { quantity: 9 })
    expect(next.items[0]).toMatchObject({ quantity: 9, note: 'x', preferred_offer_id: 5 })
  })

  it('quantity null hoặc id không tồn tại: không đổi gì và không đổi bản gốc', () => {
    expect(patchItemInDetail(detail, 1, { quantity: null }).items[0]?.quantity).toBe(2)
    expect(patchItemInDetail(detail, 999, { quantity: 5 }).items.map((i) => i.quantity)).toEqual([
      2, 1, 4,
    ])
    expect(detail.items[0]?.quantity).toBe(2)
  })
})

describe('removeItemFromDetail', () => {
  it('bỏ mục, cập nhật số mục và tổng tiền', () => {
    const detail = listDetail({ items: [a, b, gone] })
    const next = removeItemFromDetail(detail, 1)
    expect(next.items.map((item) => item.item_id)).toEqual([2, 3])
    expect(next.item_count).toBe(2)
    expect(next.total_price).toBe(5_000_000)
    expect(detail.items).toHaveLength(3)
  })

  it('id không tồn tại: giữ nguyên danh sách mục', () => {
    const detail = listDetail({ items: [a] })
    expect(removeItemFromDetail(detail, 42).items).toHaveLength(1)
  })
})
