import { ApiError } from '@/api/client'
import { formatDateTimeFull } from '@/lib/format'
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'

function detail(error: ApiError, key: string): unknown {
  const { details } = error
  return typeof details === 'object' && details !== null
    ? (details as Record<string, unknown>)[key]
    : undefined
}

/**
 * Thông điệp cho lỗi đồng bộ của `POST /admin/scrape-runs` (docs/07 §3.6): `OFFLINE_MODE`,
 * `SCRAPE_ALREADY_RUNNING` (kèm `details.run_id`) và `SITE_COOLDOWN` (kèm `details.retry_after`)
 * có câu riêng; lỗi khác dùng thông điệp của máy chủ.
 */
export function startRunErrorMessage(error: unknown): string {
  const text = strings.admin.startErrors
  if (error instanceof ApiError) {
    if (error.code === 'OFFLINE_MODE') return text.offline
    if (error.code === 'SCRAPE_ALREADY_RUNNING') {
      const runId = detail(error, 'run_id')
      return text.alreadyRunning(typeof runId === 'number' ? runId : null)
    }
    if (error.code === 'SITE_COOLDOWN') {
      const until = detail(error, 'retry_after')
      const time = typeof until === 'string' ? formatDateTimeFull(until) : null
      return text.cooldown(time === '—' ? null : time)
    }
  }
  return errorMessage(error)
}
