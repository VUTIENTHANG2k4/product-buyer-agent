import { useId, useState, type ReactNode } from 'react'
import { QueryBoundary } from '@/components/common/QueryBoundary'
import { EmptyState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Schemas } from '@/api/types'
import { formatDateTimeFull } from '@/lib/format'
import { strings } from '@/lib/strings'
import { useMediaQuery } from '@/lib/useMediaQuery'
import {
  RUNS_PAGE_SIZE,
  useRuns,
  type RunFilters,
  type ScrapeRunView,
  type ScrapeStatus,
  type SourceView,
} from './api'
import { RunCounters } from './RunCounters'
import { RunStatusBadge } from './RunStatusBadge'

const SITES = Object.keys(strings.sites) as Schemas['SiteKey'][]
const CATEGORIES = Object.keys(strings.categories) as Schemas['Category'][]
const STATUSES = Object.keys(strings.admin.statuses) as ScrapeStatus[]

interface FilterSelectProps<T extends string> {
  label: string
  value: T | null
  options: readonly T[]
  optionLabel: (value: T) => string
  onChange: (value: T | null) => void
}

function FilterSelect<T extends string>({
  label,
  value,
  options,
  optionLabel,
  onChange,
}: FilterSelectProps<T>) {
  const id = useId()
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <NativeSelect
        id={id}
        value={value ?? ''}
        onChange={(event) => onChange((event.target.value || null) as T | null)}
      >
        <option value="">{strings.admin.filterAll}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {optionLabel(option)}
          </option>
        ))}
      </NativeSelect>
    </div>
  )
}

interface RowProps {
  run: ScrapeRunView
  /** Thời điểm được thử lại của lượt `BLOCKED` mới nhất của trang (từ `cooldown_until` của nguồn). */
  retryAfter: string | null
  onHandle: (runId: number) => void
}

/** Ghi chú của lượt: lý do (khi lỗi/bị chặn), thời điểm thử lại, nút "Xử lý" khi cần người nhập đáp án. */
function RunNote({ run, retryAfter, onHandle }: RowProps): ReactNode {
  const text = strings.admin
  const parts: ReactNode[] = []
  if (run.error_message) {
    parts.push(
      <span key="reason" className="block break-words">
        {text.blockedReason(run.error_message)}
      </span>,
    )
  }
  if (run.status === 'BLOCKED' && retryAfter) {
    parts.push(
      <span key="retry" className="block">
        {text.retryAfter(formatDateTimeFull(retryAfter))}
      </span>,
    )
  }
  if (run.status === 'NEEDS_HUMAN') {
    parts.push(
      <Button
        key="handle"
        size="sm"
        variant="outline"
        aria-label={text.handleLabel(run.run_id)}
        onClick={() => onHandle(run.run_id)}
      >
        {text.handle}
      </Button>,
    )
  }
  return parts.length > 0 ? <div className="space-y-1 text-sm">{parts}</div> : null
}

function RunsTable({
  runs,
  retryAfterOf,
  onHandle,
}: {
  runs: readonly ScrapeRunView[]
  retryAfterOf: (run: ScrapeRunView) => string | null
  onHandle: (runId: number) => void
}) {
  const cols = strings.admin.columns
  return (
    <Table aria-label={strings.admin.runsTableLabel}>
      <TableHeader>
        <TableRow>
          <TableHead>{cols.id}</TableHead>
          <TableHead>{cols.site}</TableHead>
          <TableHead>{cols.category}</TableHead>
          <TableHead>{cols.status}</TableHead>
          <TableHead>{cols.started}</TableHead>
          <TableHead>{cols.numbers}</TableHead>
          <TableHead>{cols.note}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.run_id}>
            <TableCell>{strings.admin.runNumber(run.run_id)}</TableCell>
            <TableCell>{strings.sites[run.site]}</TableCell>
            <TableCell>{strings.categories[run.category]}</TableCell>
            <TableCell>
              <div className="space-y-1">
                <RunStatusBadge status={run.status} />
                <p className="text-xs text-muted-foreground">
                  {strings.admin.triggers[run.trigger]}
                </p>
              </div>
            </TableCell>
            <TableCell>{formatDateTimeFull(run.started_at)}</TableCell>
            <TableCell className="whitespace-normal">
              <RunCounters run={run} />
            </TableCell>
            <TableCell className="max-w-72 whitespace-normal">
              <RunNote run={run} retryAfter={retryAfterOf(run)} onHandle={onHandle} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function RunsCards({
  runs,
  retryAfterOf,
  onHandle,
}: {
  runs: readonly ScrapeRunView[]
  retryAfterOf: (run: ScrapeRunView) => string | null
  onHandle: (runId: number) => void
}) {
  const text = strings.admin
  return (
    <ul aria-label={text.runsTableLabel} className="space-y-3">
      {runs.map((run) => (
        <li key={run.run_id} className="space-y-2 rounded-lg border bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium">
              {text.runNumber(run.run_id)} · {strings.sites[run.site]} ·{' '}
              {strings.categories[run.category]}
            </p>
            <RunStatusBadge status={run.status} />
          </div>
          <p className="text-xs text-muted-foreground">
            {formatDateTimeFull(run.started_at)} · {text.triggers[run.trigger]}
          </p>
          <RunCounters run={run} />
          <RunNote run={run} retryAfter={retryAfterOf(run)} onHandle={onHandle} />
        </li>
      ))}
    </ul>
  )
}

interface RunsSectionProps {
  /** Nguồn đã tải (để biết thời điểm được thử lại của lượt `BLOCKED` mới nhất); có thể chưa có. */
  sources: readonly SourceView[]
  onHandle: (runId: number) => void
}

/** Bảng lượt thu thập: lọc theo trang/nhóm/trạng thái, phân trang, tự làm mới khi có lượt đang chạy. */
export function RunsSection({ sources, onHandle }: RunsSectionProps) {
  const text = strings.admin
  const [filters, setFilters] = useState<RunFilters>({
    site: null,
    category: null,
    status: null,
    page: 1,
  })
  const runs = useRuns(filters)
  const wide = useMediaQuery('(min-width: 640px)')
  const filtered = filters.site !== null || filters.category !== null || filters.status !== null

  const setFilter = <K extends 'site' | 'category' | 'status'>(key: K, value: RunFilters[K]) =>
    setFilters((current) => ({ ...current, [key]: value, page: 1 }))

  const retryAfterOf = (run: ScrapeRunView): string | null => {
    const source = sources.find((candidate) => candidate.key === run.site)
    return source?.last_run?.run_id === run.run_id ? (source.cooldown_until ?? null) : null
  }

  return (
    <section aria-labelledby="runs-heading" className="space-y-4">
      <h2 id="runs-heading" className="text-xl font-semibold">
        {text.runsTitle}
      </h2>
      <div className="flex flex-wrap gap-3">
        <FilterSelect
          label={text.filterSite}
          value={filters.site}
          options={SITES}
          optionLabel={(value) => strings.sites[value]}
          onChange={(value) => setFilter('site', value)}
        />
        <FilterSelect
          label={text.filterCategory}
          value={filters.category}
          options={CATEGORIES}
          optionLabel={(value) => strings.categories[value]}
          onChange={(value) => setFilter('category', value)}
        />
        <FilterSelect
          label={text.filterStatus}
          value={filters.status}
          options={STATUSES}
          optionLabel={(value) => text.statuses[value]}
          onChange={(value) => setFilter('status', value)}
        />
      </div>
      <QueryBoundary
        query={runs}
        errorTitle={text.runsLoadError}
        isEmpty={(data) => data.items.length === 0 && filters.page === 1}
        empty={<EmptyState title={filtered ? text.runsEmptyFiltered : text.runsEmpty} />}
        skeleton={
          <div className="space-y-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        }
      >
        {(data) => {
          const pages = Math.max(1, Math.ceil(data.total / RUNS_PAGE_SIZE))
          return (
            <div className="space-y-3">
              {wide ? (
                <RunsTable runs={data.items} retryAfterOf={retryAfterOf} onHandle={onHandle} />
              ) : (
                <RunsCards runs={data.items} retryAfterOf={retryAfterOf} onHandle={onHandle} />
              )}
              <nav
                aria-label={text.runsTitle}
                className="flex flex-wrap items-center justify-between gap-3 text-sm"
              >
                <span className="text-muted-foreground">{text.total(data.total)}</span>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={filters.page <= 1}
                    onClick={() =>
                      setFilters((current) => ({ ...current, page: current.page - 1 }))
                    }
                  >
                    {text.previous}
                  </Button>
                  <span aria-live="polite">{text.pageOf(filters.page, pages)}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={filters.page >= pages}
                    onClick={() =>
                      setFilters((current) => ({ ...current, page: current.page + 1 }))
                    }
                  >
                    {text.next}
                  </Button>
                </div>
              </nav>
            </div>
          )
        }}
      </QueryBoundary>
    </section>
  )
}
