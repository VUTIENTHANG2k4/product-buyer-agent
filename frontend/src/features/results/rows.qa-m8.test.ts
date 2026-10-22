import { offerView, productFull, productRow, rowOffer } from '@/mocks/data'
import { cheapestOfferPrice, nextSort, rowFromFull, sortRows, type ProductRow } from './rows'

const row = (id: number, name: string, min_price: number | null | undefined) =>
  productRow({ product_id: id, name, min_price, offers: [] })

const ids = (rows: readonly ProductRow[]) => rows.map((r) => r.product_id)

describe('sortRows · biên (QA M8)', () => {
  it('giá 0 là giá thật: xếp trước mọi giá dương khi tăng dần, sau khi giảm dần, và trước "chưa có giá"', () => {
    const rows = [row(1, 'a', 5_000_000_000), row(2, 'b', 0), row(3, 'c', null), row(4, 'd', 10)]
    expect(ids(sortRows(rows, { key: 'price', dir: 'asc' }))).toEqual([2, 4, 1, 3])
    expect(ids(sortRows(rows, { key: 'price', dir: 'desc' }))).toEqual([1, 4, 2, 3])
  })

  it('min_price vắng hẳn (undefined) xử lý như null: luôn xếp cuối', () => {
    const rows = [row(1, 'a', undefined), row(2, 'b', 3), row(3, 'c', null)]
    expect(ids(sortRows(rows, { key: 'price', dir: 'asc' }))).toEqual([2, 1, 3])
    expect(ids(sortRows(rows, { key: 'price', dir: 'desc' }))).toEqual([2, 1, 3])
  })

  it('giá bằng nhau giữ thứ tự gốc (ổn định) ở cả hai chiều', () => {
    const rows = [row(1, 'a', 100), row(2, 'b', 100), row(3, 'c', 100)]
    expect(ids(sortRows(rows, { key: 'price', dir: 'asc' }))).toEqual([1, 2, 3])
    expect(ids(sortRows(rows, { key: 'price', dir: 'desc' }))).toEqual([1, 2, 3])
  })

  it('hiệu hai giá 5 tỷ không tràn: 5.000.000.000 > 4.999.999.999', () => {
    const rows = [row(1, 'a', 5_000_000_000), row(2, 'b', 4_999_999_999)]
    expect(ids(sortRows(rows, { key: 'price', dir: 'asc' }))).toEqual([2, 1])
  })

  it('tên: NFC và NFD của cùng một chữ so sánh bằng nhau (giữ thứ tự gốc), không phân biệt hoa thường theo gốc chữ', () => {
    const composed = 'Ác quỷ'.normalize('NFC')
    const decomposed = 'Ác quỷ'.normalize('NFD')
    const rows = [row(1, decomposed, 1), row(2, composed, 1)]
    expect(ids(sortRows(rows, { key: 'name', dir: 'asc' }))).toEqual([1, 2])
    expect(ids(sortRows(rows, { key: 'name', dir: 'desc' }))).toEqual([1, 2])
  })

  it('tên: thứ tự thanh điệu tiếng Việt (a < à < ả < ã < á < ạ) và Đ sau D', () => {
    const names = ['Dạ', 'Đa', 'Da', 'Dà', 'Dá']
    const rows = names.map((name, index) => row(index + 1, name, 1))
    const sorted = sortRows(rows, { key: 'name', dir: 'asc' }).map((r) => r.name)
    expect(sorted).toEqual(['Da', 'Dà', 'Dá', 'Dạ', 'Đa'])
  })

  it('tên có emoji, số và ký tự đặc biệt không làm sắp xếp ném lỗi', () => {
    const names = ['🎮 Máy chơi game', '15" Laptop', '<script>', 'a'.repeat(5000), '', 'Ω']
    const rows = names.map((name, index) => row(index + 1, name, 1))
    expect(sortRows(rows, { key: 'name', dir: 'asc' })).toHaveLength(names.length)
  })

  it('sắp 5.000 dòng chạy được trong thời gian ngắn', () => {
    const rows = Array.from({ length: 5000 }, (_, i) =>
      row(i, `Máy ${5000 - i}`, (i * 7919) % 1000),
    )
    const started = performance.now()
    const sorted = sortRows(rows, { key: 'price', dir: 'asc' })
    expect(performance.now() - started).toBeLessThan(1000)
    expect(sorted[0]?.min_price).toBe(0)
  })
})

describe('nextSort · biên (QA M8)', () => {
  it('đổi cột giữa chừng khi đang giảm dần: cột mới bắt đầu từ tăng dần', () => {
    expect(nextSort({ key: 'price', dir: 'desc' }, 'name')).toEqual({ key: 'name', dir: 'asc' })
  })
})

describe('cheapestOfferPrice · biên (QA M8)', () => {
  it('giá 0 của một offer được tính là rẻ nhất', () => {
    const r = productRow({ offers: [rowOffer({ price: 0 }), rowOffer({ price: 100 })] })
    expect(cheapestOfferPrice(r)).toBe(0)
  })

  it('không có offers lẫn min_price: null', () => {
    const r = productRow({ offers: undefined, min_price: undefined })
    expect(cheapestOfferPrice(r)).toBeNull()
  })

  it('offers rỗng và min_price = 0: trả 0 (không bị ?? coi là thiếu)', () => {
    expect(cheapestOfferPrice(productRow({ offers: [], min_price: 0 }))).toBe(0)
  })
})

describe('rowFromFull · biên (QA M8)', () => {
  it('min_price của máy chủ bằng 0 được giữ (không rơi về giá offer)', () => {
    const product = productFull({ min_price: 0, offers: [offerView({ effective_price: 500 })] })
    expect(rowFromFull(product).min_price).toBe(0)
  })

  it('specs/offers/ảnh vắng: hàng hợp lệ với specs rỗng, offers rỗng, ảnh null', () => {
    const product = productFull({
      specs: undefined,
      offers: [],
      min_price: null,
      image_url: undefined,
    })
    expect(rowFromFull(product)).toEqual(
      expect.objectContaining({ key_specs: {}, offers: [], min_price: null, image_url: null }),
    )
  })

  it('tên tiếng Việt NFD, emoji và HTML giữ nguyên từng ký tự', () => {
    const name = 'Laptop 🎮 Đà Nẵng <b>x</b> ' + 'a'.repeat(3000)
    expect(rowFromFull(productFull({ name })).name).toBe(name)
  })

  it('offers cùng giá giữ thứ tự gốc; hàng hết hàng vẫn có mặt', () => {
    const product = productFull({
      offers: [
        offerView({ offer_id: 1, site: 'gearvn', effective_price: 100 }),
        offerView({
          offer_id: 2,
          site: 'fptshop',
          effective_price: 100,
          stock_status: 'out_of_stock',
        }),
      ],
    })
    expect((rowFromFull(product).offers ?? []).map((o) => o.site)).toEqual(['gearvn', 'fptshop'])
  })

  it('dùng effective_price (không phải price niêm yết) cho giá offer', () => {
    const product = productFull({
      offers: [offerView({ price: 30_000_000, effective_price: 25_000_000 })],
      min_price: null,
    })
    const result = rowFromFull(product)
    expect(result.offers?.[0]?.price).toBe(25_000_000)
    expect(result.min_price).toBe(25_000_000)
  })
})
