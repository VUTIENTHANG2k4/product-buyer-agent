import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronUp } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { Price } from '@/components/common/badges'
import { ProductImage } from '@/components/common/ProductImage'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { CreateAlertDialog, type AlertProduct } from '@/features/alerts/CreateAlertDialog'
import { specEntries } from '@/features/catalog/specs'
import { AddToListDialog, type DialogProduct } from '@/features/lists/AddToListDialog'
import { strings } from '@/lib/strings'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { cn } from '@/lib/utils'
import { CompareDrawer } from './CompareDrawer'
import { OffersList } from './OffersList'
import { RowMenu } from './RowMenu'
import {
  MAX_COMPARE,
  MIN_COMPARE,
  nextSort,
  sortRows,
  type ProductRow,
  type Sort,
  type SortKey,
} from './rows'

const MAX_KEY_SPECS = 4

function KeySpecs({ row }: { row: ProductRow }) {
  const entries = specEntries(row.key_specs, MAX_KEY_SPECS)
  if (entries.length === 0) return null
  return (
    <ul className="space-y-0.5 text-xs text-muted-foreground">
      {entries.map((entry) => (
        <li key={entry.field}>
          {entry.label}: <span className="text-foreground">{entry.value}</span>
        </li>
      ))}
    </ul>
  )
}

function MinPrice({ row }: { row: ProductRow }) {
  return row.min_price === null || row.min_price === undefined ? (
    <span className="text-sm text-muted-foreground">{strings.results.noPrice}</span>
  ) : (
    <Price amount={row.min_price} className="font-semibold" />
  )
}

function ProductName({ row }: { row: ProductRow }) {
  return (
    <div className="min-w-0">
      <Link
        to={`/products/${row.product_id}`}
        className="font-medium break-words hover:underline focus-visible:underline"
      >
        {row.name}
      </Link>
      <p className="text-xs text-muted-foreground">{row.brand}</p>
    </div>
  )
}

interface SellersToggleProps {
  row: ProductRow
  open: boolean
  onToggle: () => void
}

function SellersToggle({ row, open, onToggle }: SellersToggleProps) {
  const count = row.offers?.length ?? 0
  if (count === 0) return <span className="text-sm text-muted-foreground">—</span>
  const Icon = open ? ChevronUp : ChevronDown
  return (
    <Button
      variant="ghost"
      size="sm"
      aria-expanded={open}
      aria-label={`${strings.results.sellersCount(count)}, ${open ? strings.results.hideSellers : strings.results.showSellers}: ${row.name}`}
      onClick={onToggle}
    >
      {strings.results.sellersCount(count)}
      <Icon aria-hidden="true" />
    </Button>
  )
}

function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
  className,
}: {
  label: string
  sortKey: SortKey
  sort: Sort | null
  onSort: (key: SortKey) => void
  className?: string
}) {
  const active = sort?.key === sortKey ? sort.dir : null
  const Icon = active === 'asc' ? ArrowUp : active === 'desc' ? ArrowDown : ArrowUpDown
  return (
    <TableHead
      className={className}
      aria-sort={active === 'asc' ? 'ascending' : active === 'desc' ? 'descending' : 'none'}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        aria-label={strings.results.sortBy(label)}
        className="inline-flex items-center gap-1 rounded-sm font-medium outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        {label}
        <Icon className={cn('size-3.5', !active && 'text-muted-foreground')} aria-hidden="true" />
      </button>
    </TableHead>
  )
}

interface ResultsTableProps {
  rows: readonly ProductRow[]
  /** Phần thêm bên dưới bảng (vd. gợi ý tiếp). */
  footer?: ReactNode
}

/**
 * Bảng kết quả (docs/08 §3.2): sắp xếp theo tên/giá, chọn 2–5 sản phẩm để so sánh, mở giá từng trang,
 * menu thao tác. Dưới 640 px chuyển thành danh sách thẻ. Chỉ hiện số liệu có trong `rows`.
 */
export function ResultsTable({ rows, footer }: ResultsTableProps) {
  const wide = useMediaQuery('(min-width: 640px)')
  const [sort, setSort] = useState<Sort | null>(null)
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set())
  const [compareIds, setCompareIds] = useState<number[] | null>(null)
  const [listFor, setListFor] = useState<DialogProduct | null>(null)
  const [alertFor, setAlertFor] = useState<AlertProduct | null>(null)

  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort])
  if (rows.length === 0) return null

  const full = selected.size >= MAX_COMPARE

  function toggleSelected(id: number) {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else if (next.size < MAX_COMPARE) next.add(id)
      return next
    })
  }

  function toggleExpanded(id: number) {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const menu = (row: ProductRow) => (
    <RowMenu
      row={row}
      onAddToList={(target) => setListFor({ id: target.product_id, name: target.name })}
      onCreateAlert={(target) =>
        setAlertFor({
          id: target.product_id,
          name: target.name,
          currentPrice: target.min_price ?? null,
        })
      }
    />
  )

  const checkbox = (row: ProductRow) => (
    <Checkbox
      checked={selected.has(row.product_id)}
      disabled={full && !selected.has(row.product_id)}
      onCheckedChange={() => toggleSelected(row.product_id)}
      aria-label={strings.results.select(row.name)}
    />
  )

  return (
    <div className="space-y-3">
      {wide ? (
        <div className="overflow-x-auto rounded-lg border">
          <Table aria-label={strings.results.tableLabel}>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <SortHeader
                  label={strings.results.product}
                  sortKey="name"
                  sort={sort}
                  onSort={(key) => setSort((current) => nextSort(current, key))}
                />
                <SortHeader
                  label={strings.results.lowestPrice}
                  sortKey="price"
                  sort={sort}
                  onSort={(key) => setSort((current) => nextSort(current, key))}
                />
                <TableHead>{strings.results.mainSpecs}</TableHead>
                <TableHead>{strings.results.sellers}</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((row) => {
                const open = expanded.has(row.product_id)
                return (
                  <ResultRowGroup key={row.product_id} open={open} offers={row.offers ?? []}>
                    <TableCell>{checkbox(row)}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <ProductImage url={row.image_url} />
                        <ProductName row={row} />
                      </div>
                    </TableCell>
                    <TableCell>
                      <MinPrice row={row} />
                    </TableCell>
                    <TableCell>
                      <KeySpecs row={row} />
                    </TableCell>
                    <TableCell>
                      <SellersToggle
                        row={row}
                        open={open}
                        onToggle={() => toggleExpanded(row.product_id)}
                      />
                    </TableCell>
                    <TableCell>{menu(row)}</TableCell>
                  </ResultRowGroup>
                )
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <ul aria-label={strings.results.tableLabel} className="space-y-3">
          {sorted.map((row) => {
            const open = expanded.has(row.product_id)
            return (
              <li key={row.product_id} className="space-y-3 rounded-lg border bg-card p-3">
                <div className="flex items-start gap-3">
                  <span className="pt-1">{checkbox(row)}</span>
                  <ProductImage url={row.image_url} />
                  <div className="min-w-0 flex-1 space-y-1">
                    <ProductName row={row} />
                    <MinPrice row={row} />
                  </div>
                  {menu(row)}
                </div>
                <KeySpecs row={row} />
                <div>
                  <SellersToggle
                    row={row}
                    open={open}
                    onToggle={() => toggleExpanded(row.product_id)}
                  />
                </div>
                {open ? <OffersList offers={row.offers ?? []} /> : null}
              </li>
            )
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm" aria-live="polite">
          {strings.results.selectedCount(selected.size)}
        </span>
        <Button
          size="sm"
          disabled={selected.size < MIN_COMPARE}
          onClick={() =>
            setCompareIds(sorted.filter((r) => selected.has(r.product_id)).map((r) => r.product_id))
          }
        >
          {strings.results.compare}
        </Button>
        <span className="text-xs text-muted-foreground">
          {full
            ? strings.results.compareLimit
            : selected.size < MIN_COMPARE
              ? strings.results.compareHint
              : ''}
        </span>
      </div>
      {footer}

      <CompareDrawer ids={compareIds} onClose={() => setCompareIds(null)} />
      <AddToListDialog product={listFor} onOpenChange={(open) => !open && setListFor(null)} />
      <CreateAlertDialog product={alertFor} onOpenChange={(open) => !open && setAlertFor(null)} />
    </div>
  )
}

/** Một sản phẩm trong bảng rộng: hàng chính, và hàng phụ liệt kê giá từng trang khi mở. */
function ResultRowGroup({
  open,
  offers,
  children,
}: {
  open: boolean
  offers: ProductRow['offers']
  children: ReactNode
}) {
  return (
    <>
      <TableRow>{children}</TableRow>
      {open ? (
        <TableRow className="bg-muted/40 hover:bg-muted/40">
          <TableCell />
          <TableCell colSpan={5}>
            <OffersList offers={offers ?? []} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
