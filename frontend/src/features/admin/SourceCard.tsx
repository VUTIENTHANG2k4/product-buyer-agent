import { useState } from 'react'
import { ToneBadge, type Tone } from '@/components/common/badges'
import { Button } from '@/components/ui/button'
import { formatDateTimeFull } from '@/lib/format'
import { strings } from '@/lib/strings'
import { useStartRun, type SourceView } from './api'
import { RunCounters } from './RunCounters'
import { RunStatusBadge } from './RunStatusBadge'
import { startRunErrorMessage } from './startRunError'

const robotsTone: Record<SourceView['robots_status'], Tone> = {
  allowed: 'success',
  partial: 'warning',
  unknown: 'neutral',
}

/** Độ trễ có tối đa một chữ số thập phân, dấu phẩy kiểu Việt Nam ("5", "7,5"). */
function formatDelay(seconds: number): string {
  return String(Math.round(seconds * 10) / 10).replace('.', ',')
}

interface SourceCardProps {
  source: SourceView
  /** Mở hộp thoại challenge cho lượt `NEEDS_HUMAN`. */
  onHandle: (runId: number) => void
  now?: Date
}

type Feedback = { kind: 'ok' | 'error'; text: string }

/** Thẻ một nguồn: cấu hình, robots, lượt chạy gần nhất và nút "Chạy ngay" theo nhóm (docs/08 §3.7). */
export function SourceCard({ source, onHandle, now = new Date() }: SourceCardProps) {
  const text = strings.admin
  const siteName = strings.sites[source.key]
  const start = useStartRun()
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const run = source.last_run
  const cooling = source.cooldown_until !== null && new Date(source.cooldown_until) > now

  function runNow(category: SourceView['categories'][number]) {
    setFeedback(null)
    start.mutate(
      { site: source.key, category },
      {
        onSuccess: ({ run_id }) =>
          setFeedback({
            kind: 'ok',
            text: text.started(siteName, strings.categories[category], run_id),
          }),
        onError: (error) => setFeedback({ kind: 'error', text: startRunErrorMessage(error) }),
      },
    )
  }

  return (
    <li className="space-y-4 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-semibold">{siteName}</h3>
        {source.is_mock ? <ToneBadge tone="neutral">{text.mockBadge}</ToneBadge> : null}
        {source.enabled ? null : <ToneBadge tone="danger">{text.disabledBadge}</ToneBadge>}
        <ToneBadge tone={robotsTone[source.robots_status]}>
          {text.robots[source.robots_status]}
        </ToneBadge>
      </div>
      <p className="text-sm text-muted-foreground">
        {text.delay(formatDelay(source.effective_delay_s))}
        {source.supports_live_search ? ` · ${text.liveSearch}` : ''}
      </p>

      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">{text.lastRun}</p>
        {run ? (
          <div className="space-y-1.5 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <RunStatusBadge status={run.status} />
              <span>
                {text.runNumber(run.run_id)} · {strings.categories[run.category]} ·{' '}
                {formatDateTimeFull(run.started_at)}
              </span>
            </div>
            <RunCounters run={run} />
            {run.error_message && ['BLOCKED', 'FAILED', 'PARTIAL'].includes(run.status) ? (
              <p className={run.status === 'PARTIAL' ? 'text-warning' : 'text-destructive'}>
                {text.blockedReason(run.error_message)}
              </p>
            ) : null}
            {run.status === 'NEEDS_HUMAN' ? (
              <Button
                size="sm"
                variant="outline"
                aria-label={text.handleLabel(run.run_id)}
                onClick={() => onHandle(run.run_id)}
              >
                {text.handle}
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{text.noRun}</p>
        )}
        {cooling && source.cooldown_until ? (
          <p role="status" className="text-sm text-warning">
            {text.cooldown(formatDateTimeFull(source.cooldown_until))}
          </p>
        ) : null}
      </div>

      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">{text.categoriesLabel}</p>
        <div className="flex flex-wrap gap-2">
          {source.categories.map((category) => {
            const pending = start.isPending && start.variables?.category === category
            return (
              <Button
                key={category}
                size="sm"
                variant="outline"
                disabled={!source.enabled || start.isPending}
                aria-label={text.runNowLabel(siteName, strings.categories[category])}
                onClick={() => runNow(category)}
              >
                {pending ? text.starting : `${strings.categories[category]}: ${text.runNow}`}
              </Button>
            )
          })}
        </div>
        {feedback ? (
          <p
            role={feedback.kind === 'error' ? 'alert' : 'status'}
            className={feedback.kind === 'error' ? 'text-sm text-destructive' : 'text-sm'}
          >
            {feedback.text}
          </p>
        ) : null}
      </div>
    </li>
  )
}
