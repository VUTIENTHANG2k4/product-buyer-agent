import { strings } from '@/lib/strings'
import type { ScrapeRunView } from './api'

/** Bộ đếm của một lượt: trang đã tải, mục đã đọc/lỗi, offer ghi nhận, số lần đổi giá. */
export function RunCounters({ run }: { run: ScrapeRunView }) {
  const text = strings.admin.counters
  return (
    <p className="text-xs text-muted-foreground">
      {[
        text.pages(run.pages_fetched),
        text.parsed(run.items_parsed),
        text.failed(run.items_failed),
        text.offers(run.offers_upserted),
        text.changes(run.price_changes),
      ].join(' · ')}
    </p>
  )
}
