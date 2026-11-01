import { ExternalLink } from 'lucide-react'
import { Price, ToneBadge } from '@/components/common/badges'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Schemas } from '@/api/types'
import { safeUrl } from '@/lib/safeUrl'
import { strings } from '@/lib/strings'

/** `LiveItem.site` là chuỗi tự do của API: biết khóa trang thì hiện tên, không thì giữ nguyên. */
function siteName(site: string): string {
  return site in strings.sites ? strings.sites[site as Schemas['SiteKey']] : site
}

/** Kết quả tìm trực tiếp tầng 2 (docs/08 §3.2): bảng đơn giản, nhãn vàng "chưa chuẩn hóa thông số". */
export function LiveItemsTable({ items }: { items: readonly Schemas['LiveItem'][] }) {
  if (items.length === 0) return null
  const text = strings.results
  return (
    <div className="space-y-2">
      <ToneBadge tone="warning">{text.liveLabel}</ToneBadge>
      <div className="overflow-x-auto rounded-lg border">
        <Table aria-label={text.liveLabel}>
          <TableHeader>
            <TableRow>
              <TableHead>{text.liveName}</TableHead>
              <TableHead>{text.livePrice}</TableHead>
              <TableHead>{text.liveSite}</TableHead>
              <TableHead>{text.liveLink}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item, index) => {
              const href = safeUrl(item.url)
              return (
                <TableRow key={`${item.url}-${index}`}>
                  <TableCell className="whitespace-normal">{item.title}</TableCell>
                  <TableCell>
                    {item.price === null || item.price === undefined ? (
                      <span className="text-muted-foreground">{text.liveNoPrice}</span>
                    ) : (
                      <Price amount={item.price} />
                    )}
                  </TableCell>
                  <TableCell>{siteName(item.site)}</TableCell>
                  <TableCell>
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`${text.openSite}: ${item.title}`}
                        className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
                      >
                        {text.openSite}
                        <ExternalLink className="size-3.5" aria-hidden="true" />
                      </a>
                    ) : null}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
