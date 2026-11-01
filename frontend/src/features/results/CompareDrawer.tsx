import { Check } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Price } from '@/components/common/badges'
import { QueryBoundary } from '@/components/common/QueryBoundary'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { compareSpecFields, formatSpecValue, specLabel } from '@/features/catalog/specs'
import { strings } from '@/lib/strings'
import { useCompare, type Comparison } from './api'

/** Trường suy ra từ trường khác (hạng GPU) làm bảng rối, không hiện. */
const HIDDEN_FIELDS = new Set(['gpu_rank'])

function specFieldsOf(comparison: Comparison): string[] {
  const fields = new Set<string>()
  for (const product of comparison.products) {
    for (const [field, value] of Object.entries(product.specs ?? {})) {
      if (value !== null && value !== undefined && !HIDDEN_FIELDS.has(field)) fields.add(field)
    }
  }
  return [...fields].sort(compareSpecFields)
}

function CompareTable({ comparison }: { comparison: Comparison }) {
  const id = useId()
  const [onlyDifferences, setOnlyDifferences] = useState(true)
  const differing = useMemo(() => new Set(comparison.differing_fields), [comparison])
  const allFields = useMemo(() => specFieldsOf(comparison), [comparison])
  const fields = onlyDifferences ? allFields.filter((field) => differing.has(field)) : allFields
  const text = strings.compare

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Checkbox
          id={`${id}-diff`}
          checked={onlyDifferences}
          onCheckedChange={(checked) => setOnlyDifferences(checked === true)}
        />
        <Label htmlFor={`${id}-diff`}>{text.onlyDifferences}</Label>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{text.attribute}</TableHead>
              {comparison.products.map((product) => (
                <TableHead
                  key={product.product_id}
                  scope="col"
                  className="min-w-40 whitespace-normal"
                >
                  <Link
                    to={`/products/${product.product_id}`}
                    className="font-medium hover:underline"
                  >
                    {product.name}
                  </Link>
                  <p className="text-xs font-normal text-muted-foreground">{product.brand}</p>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableHead scope="row">{text.price}</TableHead>
              {comparison.products.map((product) => {
                const cheapest = product.product_id === comparison.cheapest_product_id
                return (
                  <TableCell key={product.product_id}>
                    {product.min_price === null || product.min_price === undefined ? (
                      text.missing
                    ) : (
                      <span className={cheapest ? 'font-semibold text-success' : undefined}>
                        <Price amount={product.min_price} />
                      </span>
                    )}
                    {cheapest ? (
                      <span className="ml-2 inline-flex items-center gap-1 text-xs font-medium text-success">
                        <Check className="size-3.5" aria-hidden="true" />
                        {text.cheapestMark}
                      </span>
                    ) : null}
                  </TableCell>
                )
              })}
            </TableRow>
            {fields.map((field) => (
              <TableRow key={field}>
                <TableHead scope="row">
                  {specLabel(field)}
                  {differing.has(field) && !onlyDifferences ? (
                    <span className="ml-2 text-xs font-normal text-accent-deal">
                      {strings.compare.differs}
                    </span>
                  ) : null}
                </TableHead>
                {comparison.products.map((product) => (
                  <TableCell key={product.product_id}>
                    {formatSpecValue(field, product.specs?.[field])}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {onlyDifferences && fields.length === 0 ? (
        <p className="text-sm text-muted-foreground">{text.noDifferences}</p>
      ) : null}
    </div>
  )
}

interface CompareDrawerProps {
  /** Id các sản phẩm cần so sánh (2–5); `null` là đang đóng. */
  ids: number[] | null
  onClose: () => void
}

/** Ngăn so sánh bên phải (toàn màn hình trên điện thoại), dữ liệu từ `POST /compare`. */
export function CompareDrawer({ ids, onClose }: CompareDrawerProps) {
  const compare = useCompare(ids ?? [])
  return (
    <Sheet open={ids !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-3xl"
      >
        <SheetHeader>
          <SheetTitle>{strings.compare.title(ids?.length ?? 0)}</SheetTitle>
          <SheetDescription>{strings.compare.description}</SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-4">
          {ids ? (
            <QueryBoundary
              query={compare}
              skeleton={
                <div className="space-y-2">
                  <Skeleton className="h-8 w-full" />
                  <Skeleton className="h-40 w-full" />
                </div>
              }
            >
              {(data) => <CompareTable comparison={data} />}
            </QueryBoundary>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
