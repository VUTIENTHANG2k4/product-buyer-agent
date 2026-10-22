import { BellPlus, ExternalLink, ListPlus, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Price, SiteBadge, StaleBadge, ToneBadge } from '@/components/common/badges'
import { ProductImage } from '@/components/common/ProductImage'
import { EmptyState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { CreateAlertDialog, type AlertProduct } from '@/features/alerts/CreateAlertDialog'
import { AddToListDialog, type DialogProduct } from '@/features/lists/AddToListDialog'
import { formatDateTime, formatVnd, isStale } from '@/lib/format'
import { safeUrl } from '@/lib/safeUrl'
import { strings } from '@/lib/strings'
import type { ProductDetail } from './api'
import { PriceHistoryChart } from './PriceHistoryChart'
import { compareSpecFields, specEntries } from './specs'

/** Trường suy ra (hạng GPU) không có ý nghĩa với người mua nên không hiện trong bảng thông số. */
const HIDDEN_SPECS = new Set(['gpu_rank'])
/** Dưới ngưỡng này thông số coi là trích tự động, cần người dùng kiểm tra (docs/08 §3.4). */
export const LOW_CONFIDENCE = 0.8

function OffersTable({ product }: { product: ProductDetail }) {
  const offers = [...(product.offers ?? [])].sort((a, b) => a.effective_price - b.effective_price)
  const text = strings.product
  if (offers.length === 0) return <EmptyState title={text.noOffers} />
  const lowest = offers[0]?.effective_price
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table aria-label={text.offersTitle}>
        <TableHeader>
          <TableRow>
            <TableHead>{text.siteColumn}</TableHead>
            <TableHead>{text.priceColumn}</TableHead>
            <TableHead>{text.priceTypeColumn}</TableHead>
            <TableHead>{text.stockColumn}</TableHead>
            <TableHead>{text.updatedColumn}</TableHead>
            <TableHead>
              <span className="sr-only">{strings.results.openSite}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {offers.map((offer) => {
            const href = safeUrl(offer.url)
            const type = strings.priceTypes[offer.price_type]
            const hasListPrice =
              offer.list_price !== null &&
              offer.list_price !== undefined &&
              offer.list_price > offer.effective_price
            return (
              <TableRow key={offer.offer_id}>
                <TableCell>
                  <SiteBadge site={offer.site} />
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <Price
                      amount={offer.effective_price}
                      className={
                        offer.effective_price === lowest
                          ? 'font-semibold text-success'
                          : 'font-medium'
                      }
                    />
                    {offer.effective_price === lowest ? (
                      <span className="text-xs font-medium text-success">
                        {strings.results.cheapest}
                      </span>
                    ) : null}
                  </div>
                  {hasListPrice ? (
                    <p className="text-xs text-muted-foreground">
                      {text.listPrice(formatVnd(offer.list_price as number))}
                    </p>
                  ) : null}
                </TableCell>
                <TableCell>{type || text.regularPrice}</TableCell>
                <TableCell>
                  <ToneBadge tone={offer.stock_status === 'in_stock' ? 'success' : 'neutral'}>
                    {strings.stock[offer.stock_status]}
                  </ToneBadge>
                </TableCell>
                <TableCell className="whitespace-normal">
                  {isStale(offer.scraped_at) ? (
                    <StaleBadge at={offer.scraped_at} />
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      {formatDateTime(offer.scraped_at)}
                    </span>
                  )}
                </TableCell>
                <TableCell>
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
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function SpecsTable({ product }: { product: ProductDetail }) {
  const text = strings.product
  const entries = specEntries(product.specs)
    .filter((entry) => !HIDDEN_SPECS.has(entry.field))
    .sort((a, b) => compareSpecFields(a.field, b.field))
  return (
    <section aria-labelledby="specs-heading" className="space-y-3">
      <h2 id="specs-heading" className="text-lg font-semibold">
        {text.specsTitle}
      </h2>
      {product.specs_confidence < LOW_CONFIDENCE ? (
        <p
          role="note"
          className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          {text.lowConfidence}
        </p>
      ) : null}
      {entries.length === 0 ? (
        <EmptyState title={text.noSpecs} />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table aria-label={text.specsTitle}>
            <TableHeader>
              <TableRow>
                <TableHead>{text.specColumn}</TableHead>
                <TableHead>{text.valueColumn}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => (
                <TableRow key={entry.field}>
                  <TableHead scope="row" className="font-normal text-muted-foreground">
                    {entry.label}
                  </TableHead>
                  <TableCell className="whitespace-normal">{entry.value}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  )
}

/** Chi tiết một sản phẩm (docs/08 §3.4): giá theo trang, lịch sử giá, thông số, hành động. */
export function ProductDetailView({ product }: { product: ProductDetail }) {
  const [listFor, setListFor] = useState<DialogProduct | null>(null)
  const [alertFor, setAlertFor] = useState<AlertProduct | null>(null)
  const text = strings.product
  const hasPrice = product.min_price !== null && product.min_price !== undefined

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start gap-4">
        <ProductImage url={product.image_url} className="size-24 sm:size-32" />
        <div className="min-w-0 flex-1 space-y-2">
          <h1 className="text-2xl font-semibold break-words">{product.name}</h1>
          <p className="text-sm text-muted-foreground">
            {product.brand}
            {product.model_code ? ` · ${text.modelCode(product.model_code)}` : ''}
          </p>
          {hasPrice ? (
            <p className="text-lg">
              {product.max_price !== null &&
              product.max_price !== undefined &&
              product.max_price !== product.min_price ? (
                text.priceRange(
                  formatVnd(product.min_price as number),
                  formatVnd(product.max_price),
                )
              ) : (
                <Price amount={product.min_price as number} className="font-semibold" />
              )}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button
              variant="outline"
              onClick={() => setListFor({ id: product.product_id, name: product.name })}
            >
              <ListPlus aria-hidden="true" />
              {strings.results.addToList}
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                setAlertFor({
                  id: product.product_id,
                  name: product.name,
                  currentPrice: product.min_price ?? null,
                })
              }
            >
              <BellPlus aria-hidden="true" />
              {strings.results.createAlert}
            </Button>
          </div>
        </div>
      </header>

      <section aria-labelledby="offers-heading" className="space-y-3">
        <h2 id="offers-heading" className="text-lg font-semibold">
          {text.offersTitle}
        </h2>
        <OffersTable product={product} />
      </section>

      <PriceHistoryChart productId={product.product_id} />
      <SpecsTable product={product} />

      <AddToListDialog product={listFor} onOpenChange={(open) => !open && setListFor(null)} />
      <CreateAlertDialog product={alertFor} onOpenChange={(open) => !open && setAlertFor(null)} />
    </div>
  )
}
