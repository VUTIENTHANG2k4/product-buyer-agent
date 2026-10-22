import {
  formatDateTime,
  formatDateTimeFull,
  formatDay,
  formatNumber,
  formatRelative,
  formatTime,
  formatVnd,
  isStale,
  STALE_AFTER_MS,
} from './format'

describe('formatVnd · biên (QA M8)', () => {
  it.each([
    [Number.MAX_SAFE_INTEGER, '9.007.199.254.740.991 ₫'],
    [-5_000_000_000, '-5.000.000.000 ₫'],
    [100, '100 ₫'],
    [999_999, '999.999 ₫'],
    [1_000_000, '1.000.000 ₫'],
    [0.5, '1 ₫'],
    [-1.5, '-1 ₫'],
  ])('%d → %s', (amount, expected) => {
    expect(formatVnd(amount)).toBe(expected)
  })

  // BUG-M8-3: số không hữu hạn (giá bị chia cho 0, dữ liệu hỏng) in ra "NaN ₫" / "Infinity ₫" cho
  // người dùng thay vì "—". XPASS báo đỏ: gỡ `.fails` khi sửa.
  it.each([[Number.NaN], [Number.POSITIVE_INFINITY], [Number.NEGATIVE_INFINITY]])(
    'giá %s không hiện chữ NaN/Infinity ra giao diện',
    (amount) => {
      expect(formatVnd(amount)).not.toMatch(/NaN|Infinity/)
    },
  )

  it('luôn dùng dấu chấm phân nhóm và đúng một dấu cách trước ký hiệu ₫ (không NBSP)', () => {
    const text = formatVnd(27_490_000)
    expect(text).toBe('27.490.000 ₫')
    expect(text.includes(' ')).toBe(false)
  })
})

describe('formatNumber · biên (QA M8)', () => {
  it.each([
    [0, '0'],
    [999, '999'],
    [1000, '1.000'],
    [-1234567, '-1.234.567'],
    [1234.5, '1.235'],
  ])('%d → %s', (value, expected) => {
    expect(formatNumber(value)).toBe(expected)
  })
})

describe('giờ Việt Nam · ranh giới ngày (QA M8)', () => {
  it('23:59 giờ VN (16:59 UTC) vẫn thuộc ngày hôm đó; 17:00 UTC là 00:00 ngày kế', () => {
    expect(formatDateTime('2026-10-16T16:59:59Z')).toBe('23:59 16/10')
    expect(formatDateTime('2026-10-16T17:00:00Z')).toBe('00:00 17/10')
    expect(formatTime('2026-10-16T17:00:00Z')).toBe('00:00')
    expect(formatDay('2026-10-16T17:00:00Z')).toBe('17/10')
  })

  it('qua năm mới và năm nhuận theo giờ VN', () => {
    expect(formatDateTimeFull('2026-12-31T17:00:00Z')).toBe('00:00 01/01/2027')
    expect(formatDateTimeFull('2028-02-28T17:00:00Z')).toBe('00:00 29/02/2028')
    expect(formatDateTimeFull('2027-02-28T17:00:00Z')).toBe('00:00 01/03/2027')
  })

  it('mốc có offset +07:00 và microgiây kiểu Python được đọc đúng', () => {
    expect(formatDateTime('2026-10-16T23:59:00+07:00')).toBe('23:59 16/10')
    expect(formatDateTime('2026-10-16T02:00:00.123456+00:00')).toBe('09:00 16/10')
  })

  it('mốc offset âm (UTC−5) vẫn đổi đúng sang giờ VN', () => {
    expect(formatDateTime('2026-10-16T12:00:00-05:00')).toBe('00:00 17/10')
  })

  it('ngày không có giờ được hiểu là 00:00 UTC = 07:00 giờ VN', () => {
    expect(formatDateTime('2026-10-16')).toBe('07:00 16/10')
  })

  it.each(['', ' ', 'null', 'undefined', '2026-13-45T00:00:00Z', 'abc', '0000-00-00'])(
    'chuỗi %j → dấu gạch ở mọi hàm định dạng',
    (value) => {
      expect(formatTime(value)).toBe('—')
      expect(formatDateTime(value)).toBe('—')
      expect(formatDateTimeFull(value)).toBe('—')
      expect(formatDay(value)).toBe('—')
      expect(formatRelative(value, new Date('2026-10-16T12:00:00Z'))).toBe('—')
    },
  )
})

describe('formatRelative · ranh giới (QA M8)', () => {
  const now = new Date('2026-10-16T12:00:00Z')
  const ago = (ms: number) => new Date(now.getTime() - ms).toISOString()

  it.each([
    [0, 'vừa xong'],
    [59_999, 'vừa xong'],
    [60_000, '1 phút trước'],
    [59 * 60_000 + 59_999, '59 phút trước'],
    [60 * 60_000, '1 giờ trước'],
    [23 * 3_600_000 + 3_599_999, '23 giờ trước'],
    [24 * 3_600_000, '1 ngày trước'],
    [47 * 3_600_000 + 3_599_999, '1 ngày trước'],
    [48 * 3_600_000, '2 ngày trước'],
    [400 * 86_400_000, '400 ngày trước'],
  ])('cách đây %d ms → %s', (ms, expected) => {
    expect(formatRelative(ago(ms), now)).toBe(expected)
  })

  it('thời điểm ở tương lai xa (đồng hồ máy khách chậm) vẫn là "vừa xong"', () => {
    expect(formatRelative('2099-01-01T00:00:00Z', now)).toBe('vừa xong')
  })
})

describe('isStale · ranh giới (QA M8)', () => {
  const now = new Date('2026-10-16T12:00:00Z')

  it('đúng 24 giờ không cũ; 24 giờ + 1 ms cũ; tương lai không cũ', () => {
    expect(isStale(new Date(now.getTime() - STALE_AFTER_MS).toISOString(), now)).toBe(false)
    expect(isStale(new Date(now.getTime() - STALE_AFTER_MS - 1).toISOString(), now)).toBe(true)
    expect(isStale('2099-01-01T00:00:00Z', now)).toBe(false)
  })

  it('mốc cũ nhiều năm là cũ', () => {
    expect(isStale('2001-01-01T00:00:00Z', now)).toBe(true)
  })
})
