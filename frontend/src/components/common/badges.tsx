import { Clock } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Schemas } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { formatDateTime, formatVnd, isStale } from '@/lib/format'
import { strings } from '@/lib/strings'
import { cn } from '@/lib/utils'

export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'deal'

const toneClass: Record<Tone, string> = {
  neutral: 'bg-secondary text-secondary-foreground',
  success: 'bg-success/15 text-success',
  warning: 'bg-warning/15 text-warning',
  danger: 'bg-destructive/15 text-destructive',
  deal: 'bg-accent-deal/15 text-accent-deal',
}

/** Badge theo ngữ nghĩa; nghĩa luôn có chữ, không chỉ dựa vào màu (docs/08 §6). */
export function ToneBadge({
  tone,
  className,
  children,
}: {
  tone: Tone
  className?: string
  children: ReactNode
}) {
  return (
    <Badge variant="secondary" className={cn(toneClass[tone], className)}>
      {children}
    </Badge>
  )
}

/** Badge vàng "Giá cập nhật lúc HH:mm dd/MM" khi dữ liệu cũ hơn 24 giờ; không hiện gì nếu còn mới. */
export function StaleBadge({ at, now }: { at: string | null | undefined; now?: Date }) {
  if (!at || !isStale(at, now)) return null
  return (
    <ToneBadge tone="warning">
      <Clock aria-hidden="true" />
      {strings.common.staleBadge(formatDateTime(at))}
    </ToneBadge>
  )
}

export function SiteBadge({ site }: { site: Schemas['SiteKey'] }) {
  return <Badge variant="outline">{strings.sites[site]}</Badge>
}

/** Số tiền VND, chữ số cùng độ rộng để cột giá thẳng hàng. */
export function Price({ amount, className }: { amount: number; className?: string }) {
  return (
    <span className={cn('tabular-nums whitespace-nowrap', className)}>{formatVnd(amount)}</span>
  )
}
