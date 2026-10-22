import { formatNumber } from '@/lib/format'

/** Nhãn tiếng Việt của các trường thông số (khớp khung specs ở backend, docs/04 §5). */
const LABELS: Record<string, string> = {
  cpu_model: 'CPU',
  cpu_vendor: 'Hãng CPU',
  gpu_model: 'GPU',
  gpu_vram_gb: 'VRAM',
  gpu_rank: 'Hạng GPU',
  ram_gb: 'RAM',
  storage_gb: 'Ổ cứng',
  storage_type: 'Loại ổ cứng',
  screen_in: 'Màn hình',
  resolution: 'Độ phân giải',
  refresh_hz: 'Tần số quét',
  panel: 'Tấm nền',
  weight_kg: 'Khối lượng',
  os: 'Hệ điều hành',
  is_gaming: 'Laptop gaming',
  connection: 'Kết nối',
  dpi_max: 'DPI tối đa',
  sensor: 'Cảm biến',
  buttons: 'Số nút',
  weight_g: 'Khối lượng',
  rgb: 'Đèn RGB',
  shape: 'Hình dáng',
  switch_type: 'Loại switch',
  switch_name: 'Switch',
  form_factor: 'Kích thước',
  hot_swap: 'Hot-swap',
  backlight: 'Đèn nền',
  form: 'Kiểu tai nghe',
  has_mic: 'Micro',
  anc: 'Chống ồn',
  surround_7_1: 'Âm thanh 7.1',
  driver_mm: 'Driver',
}

/** Thứ tự hiển thị trong bảng so sánh/chi tiết; trường không có trong danh sách xếp sau, theo tên. */
const ORDER = Object.keys(LABELS)

export function specLabel(field: string): string {
  return LABELS[field] ?? field
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
  if (typeof value === 'boolean') return value ? 'Có' : 'Không'
  if (Array.isArray(value)) return value.map(String).join(', ')
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
  return String(value)
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
