import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import type { DialogProduct } from '@/features/lists/AddToListDialog'
import { errorMessage } from '@/lib/errorMessage'
import { formatVnd } from '@/lib/format'
import { strings } from '@/lib/strings'
import { useCreateAlert, type AlertCreate } from './api'
import { parseTargetPrice, suggestTargets } from './targets'

export interface AlertProduct extends DialogProduct {
  /** Giá thấp nhất hiện tại (₫) để gợi ý ngưỡng; `null` nếu chưa có giá. */
  currentPrice: number | null
}

interface CreateAlertDialogProps {
  /** Sản phẩm cần đặt cảnh báo; `null` là đang đóng. */
  product: AlertProduct | null
  onOpenChange: (open: boolean) => void
}

type Channel = NonNullable<AlertCreate['channel']>

function CreateAlertForm({ product, onClose }: { product: AlertProduct; onClose: () => void }) {
  const text = strings.dialogs.createAlert
  const create = useCreateAlert()
  const id = useId()
  const [target, setTarget] = useState('')
  const [channel, setChannel] = useState<Channel | ''>('')
  const [destination, setDestination] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const suggestions = product.currentPrice === null ? [] : suggestTargets(product.currentPrice)
  const parsed = parseTargetPrice(target)
  const targetInvalid = target.trim() !== '' && parsed === null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (parsed === null) {
      setError(text.invalidTarget)
      return
    }
    try {
      await create.mutateAsync({
        product_id: product.id,
        target_price: parsed,
        ...(channel ? { channel } : {}),
        ...(destination.trim() ? { destination: destination.trim() } : {}),
      })
      setDone(true)
    } catch (failure) {
      setError(errorMessage(failure))
    }
  }

  if (done) {
    return (
      <>
        <p role="status" className="text-sm">
          {text.success}
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {strings.common.close}
          </Button>
          <Button asChild>
            <Link to="/alerts">{text.viewAlerts}</Link>
          </Button>
        </DialogFooter>
      </>
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {product.currentPrice !== null ? (
        <p className="text-sm text-muted-foreground">
          {text.current(formatVnd(product.currentPrice))}
        </p>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-target`}>{text.target}</Label>
        <Input
          id={`${id}-target`}
          inputMode="numeric"
          value={target}
          aria-invalid={targetInvalid}
          onChange={(event) => setTarget(event.target.value)}
        />
        {targetInvalid ? <p className="text-xs text-destructive">{text.invalidTarget}</p> : null}
        {suggestions.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-xs text-muted-foreground">{text.suggestions}:</span>
            {suggestions.map((suggestion) => (
              <Button
                key={suggestion.percent}
                type="button"
                variant="outline"
                size="xs"
                onClick={() => setTarget(String(suggestion.price))}
              >
                {text.suggestionLabel(suggestion.percent, formatVnd(suggestion.price))}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-channel`}>{text.channel}</Label>
        <NativeSelect
          id={`${id}-channel`}
          value={channel}
          onChange={(event) => setChannel(event.target.value as Channel | '')}
        >
          <option value="">{text.channelDefault}</option>
          <option value="email">{text.channels.email}</option>
          <option value="telegram">{text.channels.telegram}</option>
        </NativeSelect>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-destination`}>{text.destination}</Label>
        <Input
          id={`${id}-destination`}
          value={destination}
          aria-describedby={`${id}-destination-hint`}
          onChange={(event) => setDestination(event.target.value)}
        />
        <p id={`${id}-destination-hint`} className="text-xs text-muted-foreground">
          {text.destinationHint}
        </p>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {strings.common.cancel}
        </Button>
        <Button type="submit" disabled={create.isPending || parsed === null}>
          {create.isPending ? text.creating : text.submit}
        </Button>
      </DialogFooter>
    </form>
  )
}

/** Hộp thoại "Báo khi giảm giá": ngưỡng (gợi ý −5%/−10%), kênh và nơi nhận. */
export function CreateAlertDialog({ product, onOpenChange }: CreateAlertDialogProps) {
  return (
    <Dialog open={product !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{strings.dialogs.createAlert.title}</DialogTitle>
          <DialogDescription>
            {product ? strings.dialogs.createAlert.description(product.name) : ''}
          </DialogDescription>
        </DialogHeader>
        {product ? (
          <CreateAlertForm key={product.id} product={product} onClose={() => onOpenChange(false)} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
