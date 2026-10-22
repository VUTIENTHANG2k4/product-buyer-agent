import { CircleAlert, Inbox } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'

interface ErrorStateProps {
  error?: unknown
  /** Thông điệp đã có sẵn (vd. từ sự kiện SSE `error`); ưu tiên hơn `error`. */
  message?: string
  onRetry?: () => void
  retryLabel?: string
  title?: string
}

/** Trạng thái lỗi (docs/08 §4): thông điệp tiếng Việt + nút "Thử lại". */
export function ErrorState({
  error,
  message,
  onRetry,
  retryLabel = strings.common.retry,
  title = strings.common.errorTitle,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-8 text-center"
    >
      <CircleAlert className="size-6 text-destructive" aria-hidden="true" />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">{message ?? errorMessage(error)}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  )
}

interface EmptyStateProps {
  title: string
  description?: string
  action?: ReactNode
}

/** Trạng thái rỗng: câu giải thích + hành động gợi ý. */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-4 py-10 text-center">
      <Inbox className="size-6 text-muted-foreground" aria-hidden="true" />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  )
}

/** Vùng skeleton: báo `aria-busy` và có chữ ẩn cho trình đọc màn hình. */
export function LoadingBlock({ children }: { children: ReactNode }) {
  return (
    <div role="status" aria-busy="true">
      <span className="sr-only">{strings.common.loading}</span>
      {children}
    </div>
  )
}
