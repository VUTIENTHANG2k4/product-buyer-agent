import { Link } from 'react-router'
import { Price, ToneBadge, type Tone } from '@/components/common/badges'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTimeFull } from '@/lib/format'
import { strings } from '@/lib/strings'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { AlertActions } from './AlertActions'
import type { AlertView } from './api'

const statusTone: Record<AlertView['status'], Tone> = {
  active: 'success',
  triggered: 'deal',
  paused: 'neutral',
}

function StatusBadge({ status }: { status: AlertView['status'] }) {
  return <ToneBadge tone={statusTone[status]}>{strings.alerts.statuses[status]}</ToneBadge>
}

function ProductLink({ alert }: { alert: AlertView }) {
  return (
    <Link
      to={`/products/${alert.product_id}`}
      className="font-medium break-words underline-offset-2 hover:underline"
    >
      {alert.product_name}
    </Link>
  )
}

function CurrentPrice({ alert }: { alert: AlertView }) {
  const text = strings.alerts
  if (alert.current_best_price === null) {
    return <span className="text-muted-foreground">{text.noPrice}</span>
  }
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2">
      <Price amount={alert.current_best_price} />
      {alert.current_best_price <= alert.target_price ? (
        <span className="text-xs font-medium text-success">{text.reached}</span>
      ) : null}
    </span>
  )
}

function Channel({ alert }: { alert: AlertView }) {
  return (
    <div className="min-w-0">
      <div>{strings.alerts.channels[alert.channel]}</div>
      <div className="text-xs break-words text-muted-foreground">{alert.destination}</div>
    </div>
  )
}

function LastNotified({ alert }: { alert: AlertView }) {
  const text = strings.alerts
  if (alert.last_notified_at === null) {
    return <span className="text-muted-foreground">{text.neverNotified}</span>
  }
  const price =
    alert.last_notified_price === null ? null : (
      <Price amount={alert.last_notified_price} className="text-xs text-muted-foreground" />
    )
  return (
    <span className="space-y-0.5">
      <span className="block">{formatDateTimeFull(alert.last_notified_at)}</span>
      {price}
    </span>
  )
}

function AlertsTable({ alerts }: { alerts: readonly AlertView[] }) {
  const text = strings.alerts
  return (
    <Table aria-label={text.tableLabel}>
      <TableHeader>
        <TableRow>
          <TableHead>{text.product}</TableHead>
          <TableHead>{text.currentPrice}</TableHead>
          <TableHead>{text.targetPrice}</TableHead>
          <TableHead>{text.channel}</TableHead>
          <TableHead>{text.status}</TableHead>
          <TableHead>{text.lastNotified}</TableHead>
          <TableHead>{text.actions}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {alerts.map((alert) => (
          <TableRow key={alert.alert_id}>
            <TableCell className="max-w-64 whitespace-normal">
              <ProductLink alert={alert} />
            </TableCell>
            <TableCell>
              <CurrentPrice alert={alert} />
            </TableCell>
            <TableCell>
              <Price amount={alert.target_price} />
            </TableCell>
            <TableCell className="whitespace-normal">
              <Channel alert={alert} />
            </TableCell>
            <TableCell>
              <StatusBadge status={alert.status} />
            </TableCell>
            <TableCell>
              <LastNotified alert={alert} />
            </TableCell>
            <TableCell className="whitespace-normal">
              <AlertActions alert={alert} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  )
}

/** Dạng thẻ cho màn hình hẹp (< 640 px): mỗi cảnh báo một thẻ, cùng nội dung với bảng. */
function AlertsCards({ alerts }: { alerts: readonly AlertView[] }) {
  const text = strings.alerts
  return (
    <ul aria-label={text.tableLabel} className="space-y-3">
      {alerts.map((alert) => (
        <li key={alert.alert_id} className="space-y-3 rounded-lg border bg-card p-4">
          <div className="flex items-start justify-between gap-3">
            <ProductLink alert={alert} />
            <StatusBadge status={alert.status} />
          </div>
          <dl className="grid grid-cols-2 gap-3">
            <Field label={text.currentPrice}>
              <CurrentPrice alert={alert} />
            </Field>
            <Field label={text.targetPrice}>
              <Price amount={alert.target_price} />
            </Field>
            <Field label={text.channel}>
              <Channel alert={alert} />
            </Field>
            <Field label={text.lastNotified}>
              <LastNotified alert={alert} />
            </Field>
          </dl>
          <AlertActions alert={alert} />
        </li>
      ))}
    </ul>
  )
}

/** Các cảnh báo: bảng từ 640 px trở lên, thẻ ở màn hình hẹp (docs/08 §3.6). */
export function AlertsList({ alerts }: { alerts: readonly AlertView[] }) {
  const wide = useMediaQuery('(min-width: 640px)')
  return wide ? <AlertsTable alerts={alerts} /> : <AlertsCards alerts={alerts} />
}
