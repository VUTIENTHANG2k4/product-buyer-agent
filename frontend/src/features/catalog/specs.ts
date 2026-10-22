import { formatNumber } from '@/lib/format'
import { strings } from '@/lib/strings'

/** Nhãn tiếng Việt của các trường thông số (khớp khung specs ở backend, docs/04 §5). */
const LABELS: Record<string, string> = strings.specs.labels

/** Nhãn tiếng Việt của giá trị liệt kê (enum) của khung specs; giá trị lạ giữ nguyên. */
const VALUE_LABELS: Record<string, Record<string, string>> = strings.specs.values

function enumLabel(field: string, value: unknown): string {
  const text = String(value)
  return VALUE_LABELS[field]?.[text] ?? text
}

/** Thứ tự hiển thị trong bảng so sánh/chi tiết; trường không có trong danh sách xếp sau, theo tên. */
const ORDER = Object.keys(LABELS)

export function specLabel(field: string): string {
  return Object.hasOwn(LABELS, field) ? LABELS[field]! : field
}

export function compareSpecFields(a: string, b: string): number {
  const ia = ORDER.indexOf(a)
  const ib = ORDER.indexOf(b)
  if (ia !== -1 && ib !== -1) return ia - ib
  if (ia !== -1) return -1
  if (ib !== -1) return 1
  return a.localeCompare(b)
}

function isMissing(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** Giá trị thông số đọc được: có đơn vị, "Có/Không" cho boolean; thiếu thì `—`. */
export function formatSpecValue(field: string, value: unknown): string {
  if (isMissing(value)) return '—'
  if (typeof value === 'boolean') return value ? strings.specs.yes : strings.specs.no
  if (Array.isArray(value)) return value.map((item) => enumLabel(field, item)).join(', ')
  if (typeof value === 'number') {
    switch (field) {
      case 'ram_gb':
      case 'gpu_vram_gb':
        return `${value} GB`
      case 'storage_gb':
        return value >= 1000 ? `${value / 1000} TB` : `${value} GB`
      case 'screen_in':
        return `${value}"`
      case 'refresh_hz':
        return `${value} Hz`
      case 'weight_kg':
        return `${value} kg`
      case 'weight_g':
        return `${value} g`
      case 'dpi_max':
        return `${formatNumber(value)} DPI`
      case 'driver_mm':
        return `${value} mm`
      default:
        return String(value)
    }
  }
  return enumLabel(field, value)
}

/** Các cặp (nhãn, giá trị) của một bộ thông số, bỏ trường thiếu; `limit` để cắt cho gọn. */
export function specEntries(
  specs: Record<string, unknown> | undefined,
  limit = Number.POSITIVE_INFINITY,
): { field: string; label: string; value: string }[] {
  return Object.entries(specs ?? {})
    .filter(([, value]) => !isMissing(value))
    .map(([field, value]) => ({
      field,
      label: specLabel(field),
      value: formatSpecValue(field, value),
    }))
    .slice(0, limit)
}
