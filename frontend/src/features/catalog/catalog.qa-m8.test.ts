import type { Schemas } from '@/api/types'
import { formatAxisPrice, mergeSeries, summarizeSites } from './chartData'
import { compareSpecFields, formatSpecValue, specEntries, specLabel } from './specs'

type Series = Schemas['SiteSeries']
const series = (site: Schemas['SiteKey'], points: [string, number][]): Series => ({
  site,
  points: points.map(([t, price]) => ({ t, price, price_type: 'regular' as const })),
})

describe('mergeSeries · biên (QA M8)', () => {
  it('lịch sử đảo ngược (mới nhất trước) vẫn ra các hàng tăng dần theo thời gian', () => {
    const { rows } = mergeSeries([
      series('gearvn', [
        ['2026-10-03T00:00:00Z', 3],
        ['2026-10-02T00:00:00Z', 2],
        ['2026-10-01T00:00:00Z', 1],
      ]),
    ])
    expect(rows.map((r) => r.gearvn)).toEqual([1, 2, 3])
  })

  it('cùng một thời điểm viết bằng múi giờ khác nhau gộp vào một hàng', () => {
    const { rows } = mergeSeries([
      series('gearvn', [['2026-10-01T00:00:00Z', 100]]),
      series('fptshop', [['2026-10-01T07:00:00+07:00', 200]]),
    ])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ gearvn: 100, fptshop: 200 })
  })

  it('một điểm duy nhất cho một trang: một hàng, một trang', () => {
    const result = mergeSeries([series('anphat', [['2026-10-01T00:00:00Z', 5_000_000_000]])])
    expect(result.rows).toEqual([{ t: Date.parse('2026-10-01T00:00:00Z'), anphat: 5_000_000_000 }])
    expect(result.sites).toEqual(['anphat'])
  })

  it('giá 0 được giữ là điểm dữ liệu thật (khóa vẫn có mặt)', () => {
    const { rows } = mergeSeries([series('gearvn', [['2026-10-01T00:00:00Z', 0]])])
    expect(rows[0]).toHaveProperty('gearvn', 0)
  })

  it('trang chỉ có điểm ở mốc khác: hàng của mốc kia không có khóa của trang đó', () => {
    const { rows } = mergeSeries([
      series('gearvn', [['2026-10-01T00:00:00Z', 1]]),
      series('fptshop', [['2026-10-02T00:00:00Z', 2]]),
    ])
    expect(rows[0]).not.toHaveProperty('fptshop')
    expect(rows[1]).not.toHaveProperty('gearvn')
  })

  it('10.000 điểm trên mỗi trang được gộp và sắp trong thời gian ngắn', () => {
    const base = Date.parse('2026-01-01T00:00:00Z')
    const points: [string, number][] = Array.from({ length: 10_000 }, (_, i) => [
      new Date(base + (10_000 - i) * 3_600_000).toISOString(),
      i,
    ])
    const started = performance.now()
    const { rows } = mergeSeries([series('gearvn', points), series('fptshop', points)])
    expect(performance.now() - started).toBeLessThan(1000)
    expect(rows).toHaveLength(10_000)
    expect(rows[0]!.t).toBeLessThan(rows[1]!.t)
  })
})

describe('summarizeSites · biên (QA M8)', () => {
  it('hai điểm cùng thời điểm: giá mới nhất là điểm đến sau trong mảng', () => {
    const [summary] = summarizeSites([
      series('gearvn', [
        ['2026-10-01T00:00:00Z', 10],
        ['2026-10-01T00:00:00Z', 20],
      ]),
    ])
    expect(summary).toMatchObject({ latest: 20, lowest: 10, highest: 20, points: 2 })
  })

  it('giá 0 tính vào mức thấp nhất', () => {
    const [summary] = summarizeSites([
      series('gearvn', [
        ['2026-10-01T00:00:00Z', 0],
        ['2026-10-02T00:00:00Z', 7],
      ]),
    ])
    expect(summary).toMatchObject({ lowest: 0, highest: 7, latest: 7 })
  })

  it('50.000 điểm của một trang không làm ném lỗi', () => {
    const base = Date.parse('2026-01-01T00:00:00Z')
    const points: [string, number][] = Array.from({ length: 50_000 }, (_, i) => [
      new Date(base + i * 60_000).toISOString(),
      1000 + (i % 100),
    ])
    const [summary] = summarizeSites([series('gearvn', points)])
    expect(summary).toMatchObject({ points: 50_000, lowest: 1000, highest: 1099 })
  })
})

describe('formatAxisPrice · biên (QA M8)', () => {
  it.each([
    [0, '0 N'],
    [500, '1 N'],
    [1_000_000, '1 tr'],
    [10_000_000, '10 tr'],
    [27_500_000, '27,5 tr'],
    [100_000_000, '100 tr'],
    [5_000_000_000, '5000 tr'],
    [-27_500_000, '-27,5 tr'],
  ])('%d → %s', (value, expected) => {
    expect(formatAxisPrice(value)).toBe(expected)
  })

  // BUG-M8-5: giá ngay dưới 1 triệu làm tròn thành "1000 N" thay vì "1 tr" (nhãn trục lệch quy ước).
  // Mức thấp: chỉ ảnh hưởng nhãn trục. XPASS báo đỏ: gỡ `.fails` khi sửa.
  it('999.600 ₫ hiện là "1 tr", không phải "1000 N"', () => {
    expect(formatAxisPrice(999_600)).toBe('1 tr')
  })
})

describe('formatSpecValue · spec lạ và giá trị biên (QA M8)', () => {
  it('trường lạ: số, chuỗi, boolean và danh sách đều hiện được', () => {
    expect(formatSpecValue('truong_la', 42)).toBe('42')
    expect(formatSpecValue('truong_la', 'Đà Nẵng 🇻🇳')).toBe('Đà Nẵng 🇻🇳')
    expect(formatSpecValue('truong_la', true)).toBe('Có')
    expect(formatSpecValue('truong_la', false)).toBe('Không')
    expect(formatSpecValue('truong_la', ['a', 'b'])).toBe('a, b')
  })

  it('boolean false là giá trị thật, không phải thiếu', () => {
    expect(formatSpecValue('has_numpad', false)).toBe('Không')
  })

  it('chuỗi HTML được giữ nguyên làm văn bản (React tự escape khi hiển thị)', () => {
    expect(formatSpecValue('cpu_model', '<img src=x onerror=alert(1)>')).toBe(
      '<img src=x onerror=alert(1)>',
    )
  })

  it.each([
    ['storage_gb', 1, '1 GB'],
    ['storage_gb', 999, '999 GB'],
    ['storage_gb', 1000, '1 TB'],
    ['storage_gb', 2000, '2 TB'],
    ['ram_gb', 0, '0 GB'],
    ['refresh_hz', 144, '144 Hz'],
    ['dpi_max', 26000, '26.000 DPI'],
    ['dpi_max', 0, '0 DPI'],
  ])('%s = %d → %s', (field, value, expected) => {
    expect(formatSpecValue(field, value)).toBe(expected)
  })

  it('mảng rỗng, chuỗi rỗng, null, undefined đều là dấu gạch', () => {
    for (const value of [[], '', null, undefined]) {
      expect(formatSpecValue('ram_gb', value)).toBe('—')
    }
  })

  it('specEntries: spec rất nhiều trường lạ giữ đủ khi không giới hạn và cắt đúng khi có giới hạn', () => {
    const specs = Object.fromEntries(Array.from({ length: 200 }, (_, i) => [`f${i}`, i]))
    expect(specEntries(specs)).toHaveLength(200)
    expect(specEntries(specs, 4)).toHaveLength(4)
    expect(specEntries(specs, 0)).toEqual([])
  })

  it('specEntries: undefined → rỗng; chỉ toàn giá trị thiếu → rỗng', () => {
    expect(specEntries(undefined)).toEqual([])
    expect(specEntries({ a: null, b: '', c: [] })).toEqual([])
  })

  // BUG-M8-6: `LABELS[field] ?? field` đọc cả thuộc tính kế thừa của Object, nên khóa spec "constructor"
  // trả về hàm thay vì chuỗi (React không hiện được nhãn). Rất thấp: khung specs ở backend là danh sách
  // trắng nên khóa lạ không tới được giao diện; chỉ là thiếu phòng thủ. XPASS báo đỏ: gỡ `.fails` khi sửa.
  it('specLabel: khóa trùng tên thuộc tính của Object ("constructor", "toString") không trả về hàm', () => {
    expect(specLabel('constructor')).toBe('constructor')
    expect(specLabel('toString')).toBe('toString')
    expect(specLabel('__proto__')).toBe('__proto__')
  })

  it('compareSpecFields: khóa trùng tên thuộc tính của Object vẫn so sánh được và xếp sau trường đã biết', () => {
    expect(compareSpecFields('constructor', 'ram_gb')).toBeGreaterThan(0)
    expect(compareSpecFields('ram_gb', 'constructor')).toBeLessThan(0)
  })
})
