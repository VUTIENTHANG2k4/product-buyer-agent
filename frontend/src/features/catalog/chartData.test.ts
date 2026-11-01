import { formatAxisPrice, mergeSeries, summarizeSites } from './chartData'

const point = (t: string, price: number) => ({ t, price, price_type: 'regular' as const })

const gearvn = {
  site: 'gearvn' as const,
  points: [
    point('2026-10-02T00:00:00Z', 28_000_000),
    point('2026-10-01T00:00:00Z', 29_000_000),
    point('2026-10-03T00:00:00Z', 27_500_000),
  ],
}
const fptshop = {
  site: 'fptshop' as const,
  points: [point('2026-10-02T00:00:00Z', 28_500_000), point('2026-10-04T00:00:00Z', 28_000_000)],
}

describe('mergeSeries', () => {
  it('gộp theo mốc thời gian, sắp tăng dần, mỗi trang một cột', () => {
    const { rows, sites } = mergeSeries([gearvn, fptshop])
    expect(sites).toEqual(['gearvn', 'fptshop'])
    expect(rows.map((row) => new Date(row.t).toISOString().slice(0, 10))).toEqual([
      '2026-10-01',
      '2026-10-02',
      '2026-10-03',
      '2026-10-04',
    ])
    expect(rows[1]).toMatchObject({ gearvn: 28_000_000, fptshop: 28_500_000 })
    expect(rows[0]).toMatchObject({ gearvn: 29_000_000 })
    expect(rows[0]).not.toHaveProperty('fptshop')
    expect(rows[3]).not.toHaveProperty('gearvn')
  })

  it('chuỗi rỗng hoặc không có điểm → không có hàng nào và không có trang', () => {
    expect(mergeSeries([])).toEqual({ rows: [], sites: [] })
    expect(mergeSeries([{ site: 'gearvn', points: [] }])).toEqual({ rows: [], sites: [] })
  })

  it('bỏ điểm có thời gian hỏng; trang chỉ có điểm hỏng không xuất hiện', () => {
    const { rows, sites } = mergeSeries([
      { site: 'gearvn', points: [point('không phải ngày', 1), point('2026-10-01T00:00:00Z', 5)] },
      { site: 'anphat', points: [point('', 9)] },
    ])
    expect(sites).toEqual(['gearvn'])
    expect(rows).toHaveLength(1)
  })

  it('cùng mốc của cùng trang: lấy giá đến sau', () => {
    const { rows } = mergeSeries([
      {
        site: 'gearvn',
        points: [point('2026-10-01T00:00:00Z', 5), point('2026-10-01T00:00:00Z', 7)],
      },
    ])
    expect(rows).toEqual([{ t: Date.parse('2026-10-01T00:00:00Z'), gearvn: 7 }])
  })

  it('không đổi dữ liệu đầu vào', () => {
    const input = [gearvn]
    mergeSeries(input)
    expect(gearvn.points[0]?.t).toBe('2026-10-02T00:00:00Z')
  })
})

describe('summarizeSites', () => {
  it('thấp nhất, cao nhất và giá mới nhất theo thời gian (không theo thứ tự mảng)', () => {
    const [summary] = summarizeSites([gearvn])
    expect(summary).toEqual({
      site: 'gearvn',
      lowest: 27_500_000,
      highest: 29_000_000,
      latest: 27_500_000,
      points: 3,
    })
  })

  it('bỏ trang không có điểm hợp lệ, giữ thứ tự các trang', () => {
    const summaries = summarizeSites([{ site: 'anphat', points: [] }, gearvn, fptshop])
    expect(summaries.map((s) => s.site)).toEqual(['gearvn', 'fptshop'])
  })

  it('một điểm duy nhất: thấp nhất = cao nhất = mới nhất', () => {
    const [summary] = summarizeSites([
      { site: 'gearvn', points: [point('2026-10-01T00:00:00Z', 5)] },
    ])
    expect(summary).toMatchObject({ lowest: 5, highest: 5, latest: 5, points: 1 })
  })
})

describe('formatAxisPrice', () => {
  it.each([
    [27_490_000, '27,5 tr'],
    [28_000_000, '28 tr'],
    [1_000_000, '1 tr'],
    [100_000_000, '100 tr'],
    [950_000, '950 N'],
    [0, '0 N'],
  ])('%d → %s', (value, expected) => {
    expect(formatAxisPrice(value)).toBe(expected)
  })
})
