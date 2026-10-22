import { offerView, productFull, productRow, rowOffer } from '@/mocks/data'
import { cheapestOfferPrice, nextSort, rowFromFull, sortRows } from './rows'

const a = productRow({ product_id: 1, name: 'Máy Đ', min_price: 30_000_000 })
const b = productRow({ product_id: 2, name: 'Máy A', min_price: 20_000_000 })
const c = productRow({ product_id: 3, name: 'Máy B', min_price: null })
const d = productRow({ product_id: 4, name: 'Máy C', min_price: 25_000_000 })
const ids = (rows: { product_id: number }[]) => rows.map((row) => row.product_id)

describe('nextSort', () => {
  it('chưa sắp → tăng → giảm → bỏ sắp xếp; đổi cột thì bắt đầu lại từ tăng', () => {
    const first = nextSort(null, 'price')
    expect(first).toEqual({ key: 'price', dir: 'asc' })
    const second = nextSort(first, 'price')
    expect(second).toEqual({ key: 'price', dir: 'desc' })
    expect(nextSort(second, 'price')).toBeNull()
    expect(nextSort(second, 'name')).toEqual({ key: 'name', dir: 'asc' })
  })
})

describe('sortRows', () => {
  it('không có sắp xếp: giữ thứ tự gốc và trả bản sao', () => {
    const input = [a, b, c, d]
    const out = sortRows(input, null)
    expect(ids(out)).toEqual([1, 2, 3, 4])
    expect(out).not.toBe(input)
  })

  it('giá tăng dần, sản phẩm chưa có giá xếp cuối', () => {
    expect(ids(sortRows([a, c, b, d], { key: 'price', dir: 'asc' }))).toEqual([2, 4, 1, 3])
  })

  it('giá giảm dần nhưng sản phẩm chưa có giá vẫn xếp cuối', () => {
    expect(ids(sortRows([a, c, b, d], { key: 'price', dir: 'desc' }))).toEqual([1, 4, 2, 3])
  })

  it('theo tên có dấu tiếng Việt (A < B < C < Đ)', () => {
    expect(ids(sortRows([a, b, c, d], { key: 'name', dir: 'asc' }))).toEqual([2, 3, 4, 1])
    expect(ids(sortRows([a, b, c, d], { key: 'name', dir: 'desc' }))).toEqual([1, 4, 3, 2])
  })

  it('không đổi mảng đầu vào', () => {
    const input = [a, b]
    sortRows(input, { key: 'price', dir: 'asc' })
    expect(ids(input)).toEqual([1, 2])
  })
})

describe('cheapestOfferPrice', () => {
  it('lấy giá offer thấp nhất; không có offer thì dùng min_price', () => {
    const row = productRow({
      offers: [rowOffer({ price: 30_000_000 }), rowOffer({ price: 28_000_000 })],
    })
    expect(cheapestOfferPrice(row)).toBe(28_000_000)
    expect(cheapestOfferPrice(productRow({ offers: [], min_price: 5 }))).toBe(5)
    expect(cheapestOfferPrice(productRow({ offers: [], min_price: null }))).toBeNull()
  })
})

describe('rowFromFull', () => {
  it('dùng giá hiệu lực của offer, sắp theo giá và lấy min_price', () => {
    const row = rowFromFull(
      productFull({
        min_price: null,
        offers: [
          offerView({
            offer_id: 1,
            site: 'gearvn',
            price: 30_000_000,
            effective_price: 29_000_000,
          }),
          offerView({
            offer_id: 2,
            site: 'fptshop',
            price: 28_500_000,
            effective_price: 28_500_000,
          }),
        ],
      }),
    )
    expect(row.offers?.map((offer) => [offer.site, offer.price])).toEqual([
      ['fptshop', 28_500_000],
      ['gearvn', 29_000_000],
    ])
    expect(row.min_price).toBe(28_500_000)
    expect(row.key_specs).toEqual(productFull().specs)
  })

  it('sản phẩm không có offer: min_price null, không lỗi', () => {
    const row = rowFromFull(productFull({ offers: [], min_price: null, specs: undefined }))
    expect(row.min_price).toBeNull()
    expect(row.offers).toEqual([])
    expect(row.key_specs).toEqual({})
  })
})
