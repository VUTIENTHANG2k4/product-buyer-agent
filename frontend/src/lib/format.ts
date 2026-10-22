import { strings } from '@/lib/strings'
/** Múi giờ hiển thị (docs/03 §Thời gian): dữ liệu lưu UTC, giao diện theo giờ Việt Nam. */
export const DISPLAY_TIME_ZONE = 'Asia/Ho_Chi_Minh'

/** Dữ liệu cũ hơn ngưỡng này thì hiện badge vàng (docs/08 §4). */
export const STALE_AFTER_MS = 24 * 60 * 60 * 1000

const vndNumber = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 })

/**
 * Tiền VND là số nguyên (CLAUDE.md): `formatVnd(27490000) → "27.490.000 ₫"`.
 * Dấu chấm phân nhóm được ghép tay để kết quả không phụ thuộc dữ liệu locale của môi trường.
 */
export function formatVnd(amount: number): string {
  if (!Number.isFinite(amount)) return '—'
  const rounded = Math.round(amount)
  const sign = rounded < 0 ? '-' : ''
  const digits = String(Math.abs(rounded)).replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${sign}${digits} ₫`
}

/** Số nguyên có dấu chấm phân nhóm theo kiểu Việt Nam, không kèm đơn vị. */
export function formatNumber(value: number): string {
  // `\s` gồm cả khoảng trắng không ngắt (U+00A0, U+202F) mà Intl có thể chèn.
  return vndNumber.format(value).replace(/\s/g, ' ')
}

function parseInstant(iso: string): Date | null {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

function partsOf(date: Date): Record<string, string> {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: DISPLAY_TIME_ZONE,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).formatToParts(date)
  return Object.fromEntries(parts.map((part) => [part.type, part.value]))
}

/** `HH:mm` theo giờ Việt Nam; chuỗi không phải ngày hợp lệ → `—`. */
export function formatTime(iso: string): string {
  const date = parseInstant(iso)
  if (!date) return '—'
  const p = partsOf(date)
  return `${p.hour}:${p.minute}`
}

/** `HH:mm dd/MM` theo giờ Việt Nam, đúng dạng badge "Giá cập nhật lúc …" (docs/08 §4). */
export function formatDateTime(iso: string): string {
  const date = parseInstant(iso)
  if (!date) return '—'
  const p = partsOf(date)
  return `${p.hour}:${p.minute} ${p.day}/${p.month}`
}

/** `HH:mm dd/MM/yyyy` theo giờ Việt Nam (bảng lượt chạy, lịch sử). */
export function formatDateTimeFull(iso: string): string {
  const date = parseInstant(iso)
  if (!date) return '—'
  const p = partsOf(date)
  return `${p.hour}:${p.minute} ${p.day}/${p.month}/${p.year}`
}

/** `dd/MM` theo giờ Việt Nam, dùng cho trục biểu đồ. */
export function formatDay(iso: string): string {
  const date = parseInstant(iso)
  if (!date) return '—'
  const p = partsOf(date)
  return `${p.day}/${p.month}`
}

/** "vừa xong", "5 phút trước", "2 giờ trước", "3 ngày trước"; thời điểm ở tương lai coi như vừa xong. */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const date = parseInstant(iso)
  if (!date) return '—'
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (seconds < 60) return strings.time.justNow
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return strings.time.minutesAgo(minutes)
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return strings.time.hoursAgo(hours)
  return strings.time.daysAgo(Math.floor(hours / 24))
}

/** Cũ hơn 24 giờ (đúng 24 giờ chưa tính là cũ). Chuỗi không hợp lệ → không báo cũ. */
export function isStale(iso: string | null | undefined, now: Date = new Date()): boolean {
  if (!iso) return false
  const date = parseInstant(iso)
  if (!date) return false
  return now.getTime() - date.getTime() > STALE_AFTER_MS
}
