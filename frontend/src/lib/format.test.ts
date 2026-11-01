import {
  formatDateTime,
  formatDateTimeFull,
  formatDay,
  formatNumber,
  formatRelative,
  formatTime,
  formatVnd,
  isStale,
} from './format'

describe('formatVnd', () => {
  it.each([
    [27490000, '27.490.000 ₫'],
    [0, '0 ₫'],
    [999, '999 ₫'],
    [1000, '1.000 ₫'],
    [5_000_000_000, '5.000.000.000 ₫'],
    [-1500000, '-1.500.000 ₫'],
  ])('%d → %s', (amount, expected) => {
    expect(formatVnd(amount)).toBe(expected)
  })

  it('làm tròn số lẻ về VND nguyên và không in -0', () => {
    expect(formatVnd(1999.6)).toBe('2.000 ₫')
    expect(formatVnd(-0.4)).toBe('0 ₫')
  })
})

describe('formatNumber', () => {
  it('phân nhóm hàng nghìn bằng dấu chấm', () => {
    expect(formatNumber(1234567)).toBe('1.234.567')
  })
})

describe('giờ Việt Nam', () => {
  // 2026-10-16T02:00:00Z = 09:00 giờ Việt Nam (UTC+7, không có giờ mùa hè).
  it('đổi UTC sang UTC+7', () => {
    expect(formatTime('2026-10-16T02:00:00Z')).toBe('09:00')
    expect(formatDateTime('2026-10-16T02:00:00Z')).toBe('09:00 16/10')
    expect(formatDateTimeFull('2026-10-16T02:00:00Z')).toBe('09:00 16/10/2026')
    expect(formatDay('2026-10-16T02:00:00Z')).toBe('16/10')
  })

  it('qua nửa đêm UTC thì sang ngày kế tiếp ở Việt Nam', () => {
    expect(formatDateTime('2026-12-31T18:30:00Z')).toBe('01:30 01/01')
    expect(formatDateTimeFull('2026-12-31T18:30:00Z')).toBe('01:30 01/01/2027')
  })

  it('00:00 hiện là 00:00, không phải 24:00', () => {
    expect(formatTime('2026-10-15T17:00:00Z')).toBe('00:00')
  })

  it('chuỗi không phải ngày hợp lệ → dấu gạch, không ném lỗi', () => {
    for (const fn of [formatTime, formatDateTime, formatDateTimeFull, formatDay, formatRelative]) {
      expect(fn('không phải ngày')).toBe('—')
    }
  })
})

describe('formatRelative', () => {
  const now = new Date('2026-10-16T12:00:00Z')

  it.each([
    ['2026-10-16T11:59:30Z', 'vừa xong'],
    ['2026-10-16T12:30:00Z', 'vừa xong'],
    ['2026-10-16T11:55:00Z', '5 phút trước'],
    ['2026-10-16T10:00:00Z', '2 giờ trước'],
    ['2026-10-13T12:00:00Z', '3 ngày trước'],
  ])('%s → %s', (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected)
  })
})

describe('isStale', () => {
  const now = new Date('2026-10-16T12:00:00Z')

  it('đúng 24 giờ chưa cũ, hơn 24 giờ một mili giây là cũ', () => {
    expect(isStale('2026-10-15T12:00:00Z', now)).toBe(false)
    expect(isStale('2026-10-15T11:59:59.999Z', now)).toBe(true)
  })

  it('không có mốc thời gian hoặc mốc hỏng → không báo cũ', () => {
    expect(isStale(null, now)).toBe(false)
    expect(isStale(undefined, now)).toBe(false)
    expect(isStale('', now)).toBe(false)
    expect(isStale('hỏng', now)).toBe(false)
  })
})
