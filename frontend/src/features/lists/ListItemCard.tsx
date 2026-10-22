import { ExternalLink, Minus, Plus, Trash2 } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { Price, SiteBadge } from '@/components/common/badges'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { useProduct } from '@/features/catalog/api'
import { formatVnd } from '@/lib/format'
import { codePointLength } from '@/lib/length'
import { safeUrl } from '@/lib/safeUrl'
import { strings } from '@/lib/strings'
import type { ItemPatch, ShoppingListItem } from './api'
import { PriceChange } from './PriceChange'

/** Giới hạn số lượng trên giao diện (API cho phép tới 2^31−1 nhưng tổng tiền có thể tràn). */
export const MAX_ITEM_QUANTITY = 10_000
const MAX_NOTE = 500

function QuantityControl({
  name,
  quantity,
  onChange,
}: {
  name: string
  quantity: number
  onChange: (quantity: number) => void
}) {
  const [text, setText] = useState(String(quantity))
  // Số lượng đổi từ ngoài (cập nhật lạc quan, hoàn tác, tải lại): đồng bộ ô nhập mà KHÔNG dựng lại
  // cụm điều khiển, nếu không focus bàn phím rơi về <body> sau mỗi lần bấm −/+.
  const [seen, setSeen] = useState(quantity)
  if (quantity !== seen) {
    setSeen(quantity)
    setText(String(quantity))
  }
  const value = Number(text)
  const valid = /^\d+$/.test(text) && value >= 1 && value <= MAX_ITEM_QUANTITY

  function commit(next: number) {
    if (next !== quantity) onChange(next)
  }

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon-sm"
        aria-label={strings.lists.decrease(name)}
        disabled={quantity <= 1}
        onClick={() => commit(quantity - 1)}
      >
        <Minus aria-hidden="true" />
      </Button>
      <Input
        inputMode="numeric"
        value={text}
        aria-label={strings.lists.quantityOf(name)}
        aria-invalid={!valid}
        className="h-8 w-16 text-center"
        onChange={(event) => setText(event.target.value)}
        onBlur={() => (valid ? commit(value) : setText(String(quantity)))}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            if (valid) commit(value)
            else setText(String(quantity))
          }
        }}
      />
      <Button
        variant="outline"
        size="icon-sm"
        aria-label={strings.lists.increase(name)}
        disabled={quantity >= MAX_ITEM_QUANTITY}
        onClick={() => commit(quantity + 1)}
      >
        <Plus aria-hidden="true" />
      </Button>
    </div>
  )
}

function NoteField({
  name,
  note,
  onChange,
}: {
  name: string
  note: string | null
  onChange: (note: string | null) => void
}) {
  const [text, setText] = useState(note ?? '')
  // Đồng bộ khi ghi chú đổi từ ngoài, không dựng lại ô nhập (giữ focus sau khi Enter lưu).
  const [seen, setSeen] = useState(note)
  if (note !== seen) {
    setSeen(note)
    setText(note ?? '')
  }
  const id = useId()
  const tooLong = codePointLength(text) > MAX_NOTE

  function commit() {
    if (tooLong) return
    const next = text.trim() === '' ? null : text.trim()
    if (next !== (note ?? null)) onChange(next)
  }

  return (
    <div className="space-y-1">
      <Input
        value={text}
        placeholder={strings.lists.notePlaceholder}
        aria-label={strings.lists.noteOf(name)}
        aria-invalid={tooLong}
        aria-describedby={tooLong ? `${id}-error` : undefined}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit()
          }
        }}
      />
      {tooLong ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {strings.lists.noteTooLong}
        </p>
      ) : null}
    </div>
  )
}

/** Chọn nơi mua ưu tiên: tải các offer của sản phẩm khi mở (không tải trước cho mọi mục). */
function SellerPicker({
  item,
  onChange,
}: {
  item: ShoppingListItem
  onChange: (offerId: number | null) => void
}) {
  const [open, setOpen] = useState(false)
  const product = useProduct(open ? item.product_id : null)
  if (!open) {
    return (
      <Button variant="ghost" size="xs" onClick={() => setOpen(true)}>
        {strings.lists.changeSeller}
      </Button>
    )
  }
  const offers = [...(product.data?.offers ?? [])].sort(
    (a, b) => a.effective_price - b.effective_price,
  )
  return (
    <NativeSelect
      aria-label={strings.lists.sellerSelect(item.name)}
      value={item.preferred_offer_id ?? ''}
      disabled={product.isPending}
      onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))}
      className="h-8 text-xs"
    >
      <option value="">{strings.lists.sellerDefault}</option>
      {offers.map((offer) => (
        <option key={offer.offer_id} value={offer.offer_id}>
          {strings.sites[offer.site]} · {formatVnd(offer.effective_price)}
          {offer.stock_status === 'out_of_stock' ? ` (${strings.lists.sellerOutOfStock})` : ''}
        </option>
      ))}
    </NativeSelect>
  )
}

interface ListItemCardProps {
  item: ShoppingListItem
  onUpdate: (itemId: number, patch: ItemPatch) => void
  onRemove: (itemId: number) => void
}

/** Một mục của danh sách: số lượng, giá lúc thêm → hiện tại, nơi mua, ghi chú, xóa (docs/08 §3.5). */
export function ListItemCard({ item, onUpdate, onRemove }: ListItemCardProps) {
  const best = item.best_offer
  const href = best ? safeUrl(best.url) : ''
  const isPreferred = best !== null && item.preferred_offer_id === best.offer_id

  return (
    <li className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <Link
          to={`/products/${item.product_id}`}
          className="font-medium break-words hover:underline focus-visible:underline"
        >
          {item.name}
        </Link>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={strings.lists.remove(item.name)}
          onClick={() => onRemove(item.item_id)}
        >
          <Trash2 aria-hidden="true" />
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">{strings.lists.quantity}</p>
          <QuantityControl
            name={item.name}
            quantity={item.quantity}
            onChange={(quantity) => onUpdate(item.item_id, { quantity })}
          />
        </div>
        <PriceChange
          priceAtAdd={item.price_at_add}
          current={item.current_price}
          delta={item.price_delta}
        />
        <div className="space-y-1.5 text-sm">
          <p className="text-xs text-muted-foreground">{strings.lists.seller}</p>
          {best ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <SiteBadge site={best.site} />
              <Price amount={best.effective_price} />
              <span className="text-xs text-muted-foreground">
                ({isPreferred ? strings.lists.preferredMark : strings.lists.cheapestMark})
              </span>
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`${strings.results.openSite} ${strings.sites[best.site]}`}
                  className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
                >
                  {strings.results.openSite}
                  <ExternalLink className="size-3.5" aria-hidden="true" />
                </a>
              ) : null}
            </div>
          ) : (
            <p className="text-muted-foreground">{strings.lists.unavailable}</p>
          )}
          <SellerPicker
            item={item}
            onChange={(offerId) => onUpdate(item.item_id, { preferred_offer_id: offerId })}
          />
        </div>
      </div>

      <NoteField
        name={item.name}
        note={item.note}
        onChange={(note) => onUpdate(item.item_id, { note })}
      />
    </li>
  )
}
