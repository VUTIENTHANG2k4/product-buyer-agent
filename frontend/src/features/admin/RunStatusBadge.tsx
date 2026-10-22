import { Loader2 } from 'lucide-react'
import { ToneBadge, type Tone } from '@/components/common/badges'
import { strings } from '@/lib/strings'
import { isActive, type ScrapeStatus } from './api'

const tones: Record<ScrapeStatus, Tone> = {
  PENDING: 'neutral',
  RUNNING: 'neutral',
  NEEDS_HUMAN: 'warning',
  BLOCKED: 'danger',
  SUCCEEDED: 'success',
  PARTIAL: 'warning',
  FAILED: 'danger',
}

/** Huy hiệu trạng thái lượt chạy; luôn có chữ, lượt đang chạy có biểu tượng quay (tắt khi giảm chuyển động). */
export function RunStatusBadge({ status }: { status: ScrapeStatus }) {
  return (
    <ToneBadge tone={tones[status]}>
      {isActive(status) ? (
        <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
      ) : null}
      {strings.admin.statuses[status]}
    </ToneBadge>
  )
}
