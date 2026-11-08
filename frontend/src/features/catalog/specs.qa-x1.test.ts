import { formatSpecValue, specEntries, specLabel } from './specs'

// QA X1: điện thoại và dữ liệu thông số lạ. `it.fails` = lỗi đã tái hiện (BUG-X1-n): khi sửa xong,
// test báo đỏ vì "đã qua" và phải đổi lại thành `it`.

const fields = (entries: { field: string }[]) => entries.map((entry) => entry.field)

describe('formatSpecValue · battery_mah và dung lượng (QA X1)', () => {
  it.each([
    [0, '0 mAh'],
    [500, '500 mAh'],
    [10_000, '10.000 mAh'],
    [30_000, '30.000 mAh'],
  ])('battery_mah = %s → %s', (value, expected) => {
    expect(formatSpecValue('battery_mah', value)).toBe(expected)
  })

  it.each([
    ['5000', '5000'],
    ['5.000 mAh', '5.000 mAh'],
    [true, 'Có'],
    [false, 'Không'],
  ])('battery_mah kiểu lạ %j không ném lỗi và hiện %s', (value, expected) => {
    expect(formatSpecValue('battery_mah', value)).toBe(expected)
  })

  it.each([
    [0, '0 GB'],
    [4000, '4 TB'],
    [3000, '3 TB'],
    [1000, '1 TB'],
    [512, '512 GB'],
    [1001, '1001 GB'],
    [16, '16 GB'],
  ])('storage_gb = %s → %s', (value, expected) => {
    expect(formatSpecValue('storage_gb', value)).toBe(expected)
  })

  it('RAM, màn hình và pin của điện thoại ở dạng chuỗi không thêm đơn vị sai', () => {
    expect(formatSpecValue('ram_gb', '8')).toBe('8')
    expect(formatSpecValue('screen_in', '6.7')).toBe('6.7')
    expect(formatSpecValue('chipset', 'Snapdragon 8 Elite')).toBe('Snapdragon 8 Elite')
    expect(formatSpecValue('os', 'iOS 18')).toBe('iOS 18')
  })

  it('chuỗi chipset/hệ điều hành lấy từ web hiện nguyên văn, kể cả HTML và chuỗi rất dài', () => {
    const html = '<img src=x onerror=alert(1)>'
    expect(formatSpecValue('chipset', html)).toBe(html)
    expect(formatSpecValue('os', 'x'.repeat(10_000))).toHaveLength(10_000)
  })

  it('chuỗi chỉ có khoảng trắng không bị coi là thiếu (backend đã cắt khoảng trắng)', () => {
    expect(formatSpecValue('chipset', ' ')).toBe(' ')
  })

  it('BUG-X1-14: giá trị trùng tên thuộc tính của Object (vd. "toString") phải hiện như chuỗi, không phải hàm', () => {
    // `VALUE_LABELS[field]?.[text] ?? text` đọc cả thuộc tính kế thừa của Object.prototype.
    expect(formatSpecValue('connection', 'toString')).toBe('toString')
    expect(formatSpecValue('switch_type', 'constructor')).toBe('constructor')
  })

  it('BUG-X1-15: giá trị là đối tượng (JSONB hỏng) không được hiện "[object Object]"', () => {
    expect(formatSpecValue('os', { a: 1 })).not.toContain('[object Object]')
  })
})

describe('specEntries · thông số rỗng, lạ, trùng (QA X1)', () => {
  it.each([undefined, null, {}])('specs = %j cho danh sách rỗng ở mọi nhóm', (specs) => {
    for (const category of [
      undefined,
      'phone',
      'laptop',
      'mouse',
      'keyboard',
      'headset',
      'other',
    ]) {
      expect(specEntries(specs as Record<string, unknown> | undefined, 4, category)).toEqual([])
    }
  })

  it('mọi giá trị đều thiếu → rỗng', () => {
    const all = { ram_gb: null, storage_gb: undefined, chipset: '', os: [] }
    expect(specEntries(all, 6, 'phone')).toEqual([])
  })

  it('limit = 0 cho danh sách rỗng', () => {
    expect(specEntries({ ram_gb: 8 }, 0, 'phone')).toEqual([])
  })

  it('limit lớn hơn số trường trả đủ, không lặp', () => {
    expect(fields(specEntries({ ram_gb: 8, os: 'Android' }, 100, 'phone'))).toEqual([
      'ram_gb',
      'os',
    ])
  })

  it('nhóm lạ hoặc không truyền nhóm giữ nguyên thứ tự khóa', () => {
    const specs = { os: 'a', ram_gb: 8, chipset: 'c' }
    for (const category of [undefined, '', 'tablet', 'other', 'PHONE', ' phone']) {
      expect(fields(specEntries(specs, 10, category))).toEqual(['os', 'ram_gb', 'chipset'])
    }
  })

  it('trường ngoài danh sách nổi bật nằm sau và giữ thứ tự ban đầu', () => {
    const specs = { z_la: 1, os: 'Android', a_la: 2, ram_gb: 8, m_la: 3, chipset: 'X' }
    expect(fields(specEntries(specs, 10, 'phone'))).toEqual([
      'ram_gb',
      'chipset',
      'os',
      'z_la',
      'a_la',
      'm_la',
    ])
  })

  it('thông số của nhóm khác truyền nhầm nhóm phone không bị mất', () => {
    const laptopSpecs = { gpu_model: 'RTX 4060', cpu_model: 'i7', ram_gb: 16 }
    expect(fields(specEntries(laptopSpecs, 10, 'phone'))).toEqual([
      'ram_gb',
      'gpu_model',
      'cpu_model',
    ])
  })

  it('tên trường khác hoa thường là trường khác', () => {
    const entries = specEntries({ RAM_GB: 8, ram_gb: 4 }, 10, 'phone')
    expect(entries).toEqual([
      { field: 'ram_gb', label: 'RAM', value: '4 GB' },
      { field: 'RAM_GB', label: 'RAM_GB', value: '8' },
    ])
  })

  it('iPhone không có RAM: bộ nhớ, chip, màn hình, pin lên đầu trước khi cắt', () => {
    const iphone = {
      os: 'iOS 18',
      battery_mah: 3561,
      screen_in: 6.1,
      chipset: 'A18',
      storage_gb: 128,
    }
    expect(specEntries(iphone, 4, 'phone')).toEqual([
      { field: 'storage_gb', label: 'Ổ cứng', value: '128 GB' },
      { field: 'chipset', label: 'Chip xử lý', value: 'A18' },
      { field: 'screen_in', label: 'Màn hình', value: '6.1"' },
      { field: 'battery_mah', label: 'Pin', value: '3.561 mAh' },
    ])
  })

  it('1 TB và pin 0 được giữ (0 là giá trị thật)', () => {
    const entries = specEntries({ battery_mah: 0, storage_gb: 1000 }, 4, 'phone')
    expect(entries.map((entry) => entry.value)).toEqual(['1 TB', '0 mAh'])
  })

  it('danh sách 10.000 trường được sắp xếp và cắt nhanh', () => {
    const big: Record<string, unknown> = {}
    for (let i = 0; i < 10_000; i += 1) big[`field_${i}`] = i
    big.ram_gb = 8
    const start = performance.now()
    const entries = specEntries(big, 4, 'phone')
    expect(performance.now() - start).toBeLessThan(2000)
    expect(entries[0]).toEqual({ field: 'ram_gb', label: 'RAM', value: '8 GB' })
    expect(entries).toHaveLength(4)
  })

  it.each(['__proto__', 'toString', 'valueOf'])(
    'nhóm trùng tên thuộc tính của Object (%s) được coi là nhóm lạ',
    (category) => {
      const specs = { os: 'a', ram_gb: 8 }
      expect(fields(specEntries(specs, 10, category))).toEqual(['os', 'ram_gb'])
    },
  )

  it('BUG-X1-16: nhóm "constructor"/"hasOwnProperty" làm specEntries ném TypeError (order.indexOf)', () => {
    const specs = { os: 'a', ram_gb: 8 }
    for (const category of ['constructor', 'hasOwnProperty']) {
      expect(fields(specEntries(specs, 10, category))).toEqual(['os', 'ram_gb'])
    }
  })
})

describe('specLabel · tên lạ (QA X1)', () => {
  it.each(['constructor', '__proto__', 'toString', ''])('"%s" giữ nguyên tên', (name) => {
    expect(specLabel(name)).toBe(name)
  })
})
