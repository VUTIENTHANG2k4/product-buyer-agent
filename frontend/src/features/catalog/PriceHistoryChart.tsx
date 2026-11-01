import { useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Schemas } from '@/api/types'
import { QueryBoundary } from '@/components/common/QueryBoundary'
import { EmptyState } from '@/components/common/states'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatDateTimeFull, formatDay, formatVnd } from '@/lib/format'
import { strings } from '@/lib/strings'
import { HISTORY_RANGES, usePriceHistory, type HistoryRange } from './api'
import { formatAxisPrice, mergeSeries, summarizeSites } from './chartData'

/** Màu đường theo token `--chart-1…5` (không dùng mã màu cứng); quá 5 trang thì lặp lại. */
const LINE_COLORS = [1, 2, 3, 4, 5].map((n) => `var(--chart-${n})`)
const lineColor = (index: number) => LINE_COLORS[index % LINE_COLORS.length] as string

function HistoryChart({ series, days }: { series: Schemas['SiteSeries'][]; days: number }) {
  const { rows, sites } = mergeSeries(series)
  const summaries = summarizeSites(series)
  const siteNames = sites.map((site) => strings.sites[site]).join(', ')
  const dots = rows.length <= 24

  return (
    <div className="space-y-4">
      <div
        role="img"
        aria-label={strings.product.historyChartLabel(days, siteNames)}
        className="h-72 w-full"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(value: number) => formatDay(new Date(value).toISOString())}
              stroke="var(--muted-foreground)"
              fontSize={12}
            />
            <YAxis
              width={56}
              domain={['auto', 'auto']}
              tickFormatter={formatAxisPrice}
              stroke="var(--muted-foreground)"
              fontSize={12}
            />
            <Tooltip
              formatter={(value, name) => [
                formatVnd(Number(value)),
                strings.sites[name as Schemas['SiteKey']] ?? String(name),
              ]}
              labelFormatter={(label) => formatDateTimeFull(new Date(Number(label)).toISOString())}
              contentStyle={{
                background: 'var(--popover)',
                color: 'var(--popover-foreground)',
                border: '1px solid var(--border)',
                borderRadius: 8,
              }}
            />
            {sites.map((site, index) => (
              <Line
                key={site}
                type="stepAfter"
                dataKey={site}
                name={site}
                stroke={lineColor(index)}
                strokeWidth={2}
                dot={dots}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-medium">{strings.product.historySummaryTitle}</h3>
        <ul className="space-y-1 text-sm">
          {summaries.map((summary, index) => (
            <li key={summary.site} className="flex flex-wrap items-center gap-x-2">
              <span
                className="inline-block h-0.5 w-4 rounded"
                style={{ background: lineColor(index) }}
                aria-hidden="true"
              />
              <span className="font-medium">{strings.sites[summary.site]}:</span>
              <span className="text-muted-foreground">
                {strings.product.historySummary(
                  formatVnd(summary.lowest),
                  formatVnd(summary.highest),
                  formatVnd(summary.latest),
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/** Biểu đồ lịch sử giá: một đường mỗi trang, chọn 7/30/90 ngày (docs/08 §3.4). */
export function PriceHistoryChart({ productId }: { productId: number }) {
  const [days, setDays] = useState<HistoryRange>(30)
  const history = usePriceHistory(productId, days)

  return (
    <section aria-labelledby="price-history-heading" className="space-y-3">
      <Tabs value={String(days)} onValueChange={(value) => setDays(Number(value) as HistoryRange)}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="price-history-heading" className="text-lg font-semibold">
            {strings.product.historyTitle}
          </h2>
          <TabsList aria-label={strings.product.historyRangeLabel}>
            {HISTORY_RANGES.map((range) => (
              <TabsTrigger key={range} value={String(range)}>
                {strings.product.historyRange(range)}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value={String(days)} className="mt-3">
          <QueryBoundary
            query={history}
            errorTitle={strings.product.historyLoadError}
            skeleton={<Skeleton className="h-72 w-full" />}
            isEmpty={(data) => mergeSeries(data.series).rows.length === 0}
            empty={
              <EmptyState
                title={strings.product.historyEmptyTitle}
                description={strings.product.historyEmptyHint}
              />
            }
          >
            {(data) => <HistoryChart series={data.series} days={days} />}
          </QueryBoundary>
        </TabsContent>
      </Tabs>
    </section>
  )
}
