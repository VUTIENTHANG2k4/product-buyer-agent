import { parseTargetPrice, suggestTargets } from './targets'

describe('parseTargetPrice · cách người Việt gõ giá (QA M8)', () => {
  it.each([
    ['27.490.000 ₫', 27_490_000],
    ['₫27.490.000', 27_490_000],
    ['27.490.000đ', 27_490_000],
    ['27.490.000 Đ', 27_490_000],
    ['27,490,000', 27_490_000],
    ['27.490,000', 27_490_000],
    ['5.000.000.000', 5_000_000_000],
    ['1.000', 1000],
    ['0.500', 500],
    ['  27 490 000  ', 27_490_000],
    ['27 490 000', 27_490_000],
    ['27 490 000', 27_490_000],
    ['9999999999999', 9_999_999_999_999],
  ])('đọc %j thành %d', (input, expected) => {
    expect(parseTargetPrice(input)).toBe(expected)
  })

  // BUG-M8-4: hai cách viết đơn vị rất phổ biến ở Việt Nam bị từ chối: "VNĐ" (chữ Đ bị xóa riêng nên
  // còn "VN") và "đồng" (còn "ồng"). Người dùng gõ "27.490.000 VNĐ" nhận lỗi "ngưỡng không hợp lệ".
  // XPASS báo đỏ: gỡ `.fails` khi sửa.
  it.each([['27.490.000 VNĐ'], ['27.490.000 vnđ'], ['27.490.000 đồng']])(
    'chấp nhận đơn vị %j',
    (input) => {
      expect(parseTargetPrice(input)).toBe(27_490_000)
    },
  )

  it.each([
    '27.490.000.',
    '.27.490',
    '27..490',
    '27.49.000',
    '27.4900.00',
    '1,5 triệu',
    '27_490_000',
    '+27490000',
    '−27490000',
    '-0',
    '0.000',
    '00',
    '２７４９０',
    '٢٧',
    '27 490 000 đồng thêm',
    '12345678901234',
    'Infinity',
    'NaN',
    '0x1F',
  ])('từ chối %j', (input) => {
    expect(parseTargetPrice(input)).toBeNull()
  })

  it('chuỗi 1 MB chữ số bị từ chối nhanh, không tràn số', () => {
    expect(parseTargetPrice('9'.repeat(1_000_000))).toBeNull()
  })

  it('kết quả luôn là số nguyên an toàn dương', () => {
    const value = parseTargetPrice('9.999.999.999.999')
    expect(Number.isSafeInteger(value)).toBe(true)
    expect(value).toBe(9_999_999_999_999)
  })
})

describe('suggestTargets · biên (QA M8)', () => {
  it('giá 5 tỷ: hai gợi ý nguyên, thấp hơn giá hiện tại, làm tròn nghìn đồng', () => {
    expect(suggestTargets(5_000_000_000)).toEqual([
      { percent: 5, price: 4_750_000_000 },
      { percent: 10, price: 4_500_000_000 },
    ])
  })

  it.each([0, -1, -5_000_000])('giá hiện tại %d: không có gợi ý nào', (price) => {
    expect(suggestTargets(price)).toEqual([])
  })

  it('giá 2 ₫: gợi ý không bao giờ bằng hoặc vượt giá hiện tại', () => {
    for (const suggestion of suggestTargets(2)) {
      expect(suggestion.price).toBeLessThan(2)
      expect(suggestion.price).toBeGreaterThanOrEqual(1)
    }
  })

  it('giá lẻ 27.490.001: gợi ý là bội số của 1.000 và thấp hơn giá', () => {
    for (const { price } of suggestTargets(27_490_001)) {
      expect(price % 1000).toBe(0)
      expect(price).toBeLessThan(27_490_001)
    }
  })
})
