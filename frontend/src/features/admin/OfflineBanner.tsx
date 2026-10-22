import { CloudOff, DatabaseZap } from 'lucide-react'
import { strings } from '@/lib/strings'
import { useHealth } from './api'

/**
 * Banner đầu trang quản trị từ `GET /health`: chế độ offline (chỉ mock-shop chạy được) và CSDL lỗi.
 * Không hiện gì khi chưa tải xong hoặc `/health` lỗi (phần còn lại của trang vẫn dùng được).
 */
export function OfflineBanner() {
  const health = useHealth()
  const data = health.data
  if (!data) return null
  const text = strings.admin
  return (
    <div className="space-y-3">
      {data.offline_mode ? (
        <div
          role="status"
          className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm"
        >
          <CloudOff className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
          <div className="space-y-1">
            <p className="font-medium">{text.offlineTitle}</p>
            <p className="text-muted-foreground">{text.offlineBody}</p>
          </div>
        </div>
      ) : null}
      {data.status === 'degraded' || data.db === 'error' ? (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm"
        >
          <DatabaseZap className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
          <p>{text.dbDegraded}</p>
        </div>
      ) : null}
      <p className="text-xs text-muted-foreground">
        {text.healthLabel(data.llm_provider, data.version)}
      </p>
    </div>
  )
}
