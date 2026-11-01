import { ArrowDown, ArrowUp } from 'lucide-react'
import { Price } from '@/components/common/badges'
import { formatVnd } from '@/lib/format'
import { strings } from '@/lib/strings'
import { cn } from '@/lib/utils'

interface PriceChangeProps {
  priceAtAdd: number | null
  current: number | null
  /** `current − priceAtAdd`: âm là rẻ hơn lúc thêm. */
  delta: number | null
}

/**
 * Giá lúc thêm → giá hiện tại. Giảm giá có mũi tên ↓ **và chữ** "Giảm …" (docs/08 §6: không chỉ
 * dùng màu để truyền nghĩa); tăng giá có ↑ và "Tăng …".
 */
export function PriceChange({ priceAtAdd, current, delta }: PriceChangeProps) {
  const text = strings.lists
  return (
    <div className="space-y-1 text-sm">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-muted-foreground">{text.priceAtAdd}:</span>
        {priceAtAdd === null ? text.unknownPrice : <Price amount={priceAtAdd} />}
      </p>
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-muted-foreground">{text.priceNow}:</span>
        {current === null ? (
          <span className="font-medium text-warning">{text.unavailable}</span>
        ) : (
          <Price amount={current} className="font-semibold" />
        )}
      </p>
      {delta === null ? null : (
        <p
          className={cn(
            'flex items-center gap-1 text-xs font-medium',
            delta < 0 && 'text-success',
            delta > 0 && 'text-warning',
            delta === 0 && 'text-muted-foreground',
          )}
        >
          {delta < 0 ? <ArrowDown className="size-3.5" aria-hidden="true" /> : null}
          {delta > 0 ? <ArrowUp className="size-3.5" aria-hidden="true" /> : null}
          {delta < 0
            ? text.cheaper(formatVnd(-delta))
            : delta > 0
              ? text.pricier(formatVnd(delta))
              : text.unchanged}
        </p>
      )}
    </div>
  )
}
