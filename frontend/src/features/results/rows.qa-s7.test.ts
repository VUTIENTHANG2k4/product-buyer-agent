import { lowestInStockPrice } from './rows'

const price = (o: { price: number }) => o.price

describe('lowestInStockPrice · biên (QA S7)', () => {
  it('một offer còn hàng và nhiều offer cùng giá thấp nhất', () => {
    expect(lowestInStockPrice([{ price: 5, stock_status: 'in_stock' }], price)).toBe(5)
    const tie = [
      { price: 5, stock_status: 'in_stock' },
      { price: 5, stock_status: 'in_stock' },
    ]
    expect(lowestInStockPrice(tie, price)).toBe(5)
  })

  it('trạng thái khác out_of_stock (vd. không rõ) vẫn tính là còn bán', () => {
    expect(lowestInStockPrice([{ price: 3, stock_status: 'unknown' }], price)).toBe(3)
  })

  it('không đổi mảng đầu vào và giá 0 vẫn là giá hợp lệ', () => {
    const offers = [
      { price: 9, stock_status: 'in_stock' },
      { price: 0, stock_status: 'in_stock' },
    ]
    const before = JSON.stringify(offers)
    expect(lowestInStockPrice(offers, price)).toBe(0)
    expect(JSON.stringify(offers)).toBe(before)
  })
})
