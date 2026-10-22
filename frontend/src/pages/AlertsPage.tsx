import { useId, useState } from 'react'
import { Link } from 'react-router'
import { QueryBoundary } from '@/components/common/QueryBoundary'
import { EmptyState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { useAlerts, type AlertStatus } from '@/features/alerts/api'
import { AlertsList } from '@/features/alerts/AlertsList'
import { strings } from '@/lib/strings'

const STATUSES: readonly AlertStatus[] = ['active', 'triggered', 'paused']

/** Cảnh báo giá: bảng (thẻ ở màn hình hẹp), lọc theo trạng thái, tạm dừng/tiếp tục/xóa/gửi thử. */
export function AlertsPage() {
  const text = strings.alerts
  const filterId = useId()
  const [status, setStatus] = useState<AlertStatus | null>(null)
  const alerts = useAlerts(status)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold">{strings.pages.alerts.title}</h1>
        <div className="space-y-1">
          <Label htmlFor={filterId} className="text-xs text-muted-foreground">
            {text.filterLabel}
          </Label>
          <NativeSelect
            id={filterId}
            value={status ?? ''}
            onChange={(event) => setStatus((event.target.value || null) as AlertStatus | null)}
          >
            <option value="">{text.filterAll}</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {text.statuses[value]}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <QueryBoundary
        query={alerts}
        errorTitle={text.loadError}
        isEmpty={(data) => data.items.length === 0}
        empty={
          status === null ? (
            <EmptyState
              title={text.emptyTitle}
              description={text.emptyHint}
              action={
                <Button asChild variant="outline" size="sm">
                  <Link to="/">{text.askAgent}</Link>
                </Button>
              }
            />
          ) : (
            <EmptyState title={text.emptyFilteredTitle} description={text.emptyFilteredHint} />
          )
        }
        skeleton={
          <div className="space-y-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        }
      >
        {(data) => <AlertsList alerts={data.items} />}
      </QueryBoundary>
    </div>
  )
}
