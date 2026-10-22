import type { Schemas } from '@/api/types'

type SiteKey = Schemas['SiteKey']
type SiteSeries = Schemas['SiteSeries']

/** Một dòng dữ liệu biểu đồ: mốc thời gian (ms) và giá của từng trang tại mốc đó (thiếu = không có khóa). */
export interface ChartRow {
  t: number
  [site: string]: number
}

export interface SiteSummary {
  site: SiteKey
  lowest: number
  highest: number
  latest: number
  points: number
}

/**
 * Gộp các chuỗi giá theo trang thành bảng theo thời gian cho Recharts (một cột mỗi trang).
 * Điểm có thời gian không hợp lệ bị bỏ; trang không có điểm nào không xuất hiện. Cùng một mốc
 * của cùng một trang thì lấy giá sau cùng.
 */
export function mergeSeries(series: readonly SiteSeries[]): { rows: ChartRow[]; sites: SiteKey[] } {
  const byTime = new Map<number, ChartRow>()
  const sites: SiteKey[] = []
  for (const entry of series) {
    let any = false
    for (const point of entry.points) {
      const t = Date.parse(point.t)
      if (Number.isNaN(t)) continue
      any = true
      const row = byTime.get(t) ?? { t }
      row[entry.site] = point.price
      byTime.set(t, row)
    }
    if (any && !sites.includes(entry.site)) sites.push(entry.site)
  }
  return { rows: [...byTime.values()].sort((a, b) => a.t - b.t), sites }
}

/** Thấp nhất, cao nhất và giá mới nhất (theo thời gian) của từng trang, cho bản tóm tắt dạng chữ. */
export function summarizeSites(series: readonly SiteSeries[]): SiteSummary[] {
  const summaries: SiteSummary[] = []
  for (const entry of series) {
    const valid = entry.points
      .map((point) => ({ t: Date.parse(point.t), price: point.price }))
      .filter((point) => !Number.isNaN(point.t))
      .sort((a, b) => a.t - b.t)
    const last = valid[valid.length - 1]
    if (!last) continue
    const prices = valid.map((point) => point.price)
    summaries.push({
      site: entry.site,
      lowest: Math.min(...prices),
      highest: Math.max(...prices),
      latest: last.price,
      points: valid.length,
    })
  }
  return summaries
}

/** Số tiền rút gọn cho trục: 27490000 → "27,5 tr", 950000 → "950 N". */
export function formatAxisPrice(value: number): string {
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1).replace('.', ',').replace(',0', '')} tr`
  }
  return `${Math.round(value / 1000)} N`
}
