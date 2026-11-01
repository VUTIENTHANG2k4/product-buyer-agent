import { ExternalLink } from 'lucide-react'
import { Price, SiteBadge, StaleBadge, ToneBadge } from '@/components/common/badges'
import { formatDateTime, isStale } from '@/lib/format'
import { safeUrl } from '@/lib/safeUrl'
import { strings } from '@/lib/strings'
import { cn } from '@/lib/utils'
import type { RowOffer } from './rows'

/** Giá từng trang của một sản phẩm: loại giá, tình trạng hàng, thời điểm cập nhật, liên kết tới trang bán. */
export function OffersList({ offers }: { offers: readonly RowOffer[] }) {
  const lowest = offers.length > 0 ? Math.min(...offers.map((offer) => offer.price)) : null
  return (
    <ul className="space-y-2">
      {offers.map((offer, index) => {
        const isLowest = offer.price === lowest
        const href = safeUrl(offer.url)
        const priceType = strings.priceTypes[offer.price_type]
        const stale = isStale(offer.scraped_at)
        return (
          <li
            key={`${offer.site}-${index}`}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
          >
            <SiteBadge site={offer.site} />
            <Price amount={offer.price} className={cn('font-medium', isLowest && 'text-success')} />
            {isLowest ? (
              <span className="text-xs font-medium text-success">{strings.results.cheapest}</span>
            ) : null}
            {priceType ? <ToneBadge tone="deal">{priceType}</ToneBadge> : null}
            <ToneBadge tone={offer.stock_status === 'in_stock' ? 'success' : 'neutral'}>
              {strings.stock[offer.stock_status]}
            </ToneBadge>
            {stale ? (
              <StaleBadge at={offer.scraped_at} />
            ) : (
              <span className="text-xs text-muted-foreground">
                {strings.results.updatedAt(formatDateTime(offer.scraped_at))}
              </span>
            )}
            {href ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${strings.results.openSite} ${strings.sites[offer.site]}`}
                className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
              >
                {strings.results.openSite}
                <ExternalLink className="size-3.5" aria-hidden="true" />
              </a>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
