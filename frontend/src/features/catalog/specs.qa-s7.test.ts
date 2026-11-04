import { formatSpecValue } from './specs'

describe('formatSpecValue · storage_gb biên (QA S7)', () => {
  it.each([
    [0, '0 GB'],
    [1, '1 GB'],
    [999, '999 GB'],
    [1000, '1 TB'],
    [1023, '1023 GB'],
    [1024, '1 TB'],
    [1025, '1025 GB'],
    [2000, '2 TB'],
    [2048, '2 TB'],
    [3000, '3 TB'],
    [3072, '3 TB'],
    [4096, '4 TB'],
    [1_000_000, '1000 TB'],
    [1.5, '1.5 GB'],
    [-1024, '-1024 GB'],
  ])('%s GB → %s', (value, expected) => {
    expect(formatSpecValue('storage_gb', value)).toBe(expected)
  })

  it('chuỗi và giá trị thiếu không đi qua nhánh TB', () => {
    expect(formatSpecValue('storage_gb', '1024')).toBe('1024')
    expect(formatSpecValue('storage_gb', null)).toBe('—')
  })
})
