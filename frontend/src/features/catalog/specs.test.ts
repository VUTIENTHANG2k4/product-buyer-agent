import { compareSpecFields, formatSpecValue, specEntries, specLabel } from './specs'

describe('specLabel', () => {
  it('nhãn tiếng Việt cho trường đã biết, trường lạ giữ nguyên tên', () => {
    expect(specLabel('gpu_model')).toBe('GPU')
    expect(specLabel('ram_gb')).toBe('RAM')
    expect(specLabel('truong_la')).toBe('truong_la')
  })
})

describe('formatSpecValue', () => {
  it.each([
    ['ram_gb', 16, '16 GB'],
    ['gpu_vram_gb', 8, '8 GB'],
    ['storage_gb', 512, '512 GB'],
    ['storage_gb', 1000, '1 TB'],
    ['storage_gb', 2000, '2 TB'],
    ['screen_in', 15.6, '15.6"'],
    ['refresh_hz', 144, '144 Hz'],
    ['weight_kg', 2.2, '2.2 kg'],
    ['weight_g', 85, '85 g'],
    ['dpi_max', 25600, '25.600 DPI'],
    ['driver_mm', 40, '40 mm'],
    ['buttons', 6, '6'],
    ['is_gaming', true, 'Có'],
    ['rgb', false, 'Không'],
    ['connection', ['wireless_2_4', 'bluetooth'], 'Không dây 2.4 GHz, Bluetooth'],
    ['connection', ['gia_tri_la'], 'gia_tri_la'],
    ['cpu_vendor', 'amd', 'AMD'],
    ['storage_type', 'ssd', 'SSD'],
    ['form_factor', '75', '75%'],
    ['backlight', 'rgb', 'RGB'],
    ['switch_type', 'mechanical', 'Cơ'],
    ['cpu_model', 'i7-13620H', 'i7-13620H'],
  ])('%s = %j → %s', (field, value, expected) => {
    expect(formatSpecValue(field, value)).toBe(expected)
  })

  it.each([null, undefined, '', []])('giá trị thiếu %j → dấu gạch', (value) => {
    expect(formatSpecValue('cpu_model', value)).toBe('—')
  })

  it('số 0 là giá trị thật (VRAM 0 GB của GPU tích hợp), không phải thiếu', () => {
    expect(formatSpecValue('gpu_vram_gb', 0)).toBe('0 GB')
  })
})

describe('specEntries', () => {
  it('bỏ trường thiếu, giữ thứ tự và cắt theo giới hạn', () => {
    const entries = specEntries({ cpu_model: 'i7', gpu_model: null, ram_gb: 16, os: '' }, 5)
    expect(entries).toEqual([
      { field: 'cpu_model', label: 'CPU', value: 'i7' },
      { field: 'ram_gb', label: 'RAM', value: '16 GB' },
    ])
    expect(specEntries({ cpu_model: 'i7', ram_gb: 16 }, 1)).toHaveLength(1)
    expect(specEntries(undefined)).toEqual([])
  })
})

describe('compareSpecFields', () => {
  it('xếp theo thứ tự nhãn đã biết, trường lạ sau cùng theo tên', () => {
    const fields = ['zeta', 'ram_gb', 'alpha', 'cpu_model', 'gpu_model']
    expect([...fields].sort(compareSpecFields)).toEqual([
      'cpu_model',
      'gpu_model',
      'ram_gb',
      'alpha',
      'zeta',
    ])
  })
})
