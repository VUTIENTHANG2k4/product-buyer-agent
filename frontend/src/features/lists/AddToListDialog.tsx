import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ErrorState } from '@/components/common/states'
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
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'
import { useAddListItem, useCreateList, useLists } from './api'

const NEW_LIST = 'new'
const MAX_QUANTITY = 10_000

export interface DialogProduct {
  id: number
  name: string
}

interface AddToListDialogProps {
  /** Sản phẩm cần thêm; `null` là đang đóng. */
  product: DialogProduct | null
  onOpenChange: (open: boolean) => void
}

function AddToListForm({ product, onClose }: { product: DialogProduct; onClose: () => void }) {
  const text = strings.dialogs.addToList
  const lists = useLists()
  const createList = useCreateList()
  const addItem = useAddListItem()
  const id = useId()
  const [choice, setChoice] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [error, setError] = useState<string | null>(null)
  const [added, setAdded] = useState<{ listId: number; name: string } | null>(null)
  // Danh sách vừa tạo ở lần gửi trước mà bước thêm mục lỗi: thử lại dùng lại nó, không tạo bản thứ hai.
  const [created, setCreated] = useState<{ list_id: number; name: string } | null>(null)

  const items = lists.data?.items ?? []
  // Mặc định chọn danh sách đầu tiên; chưa có danh sách nào thì tạo mới.
  const selected = choice ?? (items[0] ? String(items[0].list_id) : NEW_LIST)
  const creating = selected === NEW_LIST
  const pending = createList.isPending || addItem.isPending
  const quantityValue = Number(quantity)
  const quantityOk = /^\d+$/.test(quantity) && quantityValue >= 1 && quantityValue <= MAX_QUANTITY

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (creating && newName.trim() === '') {
      setError(text.nameRequired)
      return
    }
    try {
      let list: { list_id: number; name: string } | undefined
      if (creating) {
        list = created ?? (await createList.mutateAsync(newName.trim()))
        setCreated(list)
      } else {
        list = items.find((item) => String(item.list_id) === selected)
      }
      if (!list) return
      await addItem.mutateAsync({
        listId: list.list_id,
        item: { product_id: product.id, quantity: quantityValue },
      })
      setAdded({ listId: list.list_id, name: list.name })
    } catch (failure) {
      setError(errorMessage(failure))
    }
  }

  if (added) {
    return (
      <>
        <p role="status" className="text-sm">
          {text.success(added.name)}
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {strings.common.close}
          </Button>
          <Button asChild>
            <Link to={`/lists/${added.listId}`}>{text.viewList}</Link>
          </Button>
        </DialogFooter>
      </>
    )
  }

  if (lists.isError) {
    return <ErrorState error={lists.error} onRetry={() => void lists.refetch()} />
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-list`}>{text.listLabel}</Label>
        <NativeSelect
          id={`${id}-list`}
          value={selected}
          disabled={lists.isPending || pending}
          onChange={(event) => setChoice(event.target.value)}
        >
          {items.map((item) => (
            <option key={item.list_id} value={item.list_id}>
              {item.name}
            </option>
          ))}
          <option value={NEW_LIST}>{text.newList}</option>
        </NativeSelect>
        {!lists.isPending && items.length === 0 ? (
          <p className="text-xs text-muted-foreground">{text.noLists}</p>
        ) : null}
      </div>
      {creating ? (
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-name`}>{text.newListName}</Label>
          <Input
            id={`${id}-name`}
            value={newName}
            maxLength={200}
            placeholder={text.newListPlaceholder}
            onChange={(event) => setNewName(event.target.value)}
          />
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-qty`}>{text.quantity}</Label>
        <Input
          id={`${id}-qty`}
          inputMode="numeric"
          value={quantity}
          aria-invalid={!quantityOk}
          onChange={(event) => setQuantity(event.target.value)}
          className="w-28"
        />
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
        <Button type="submit" disabled={pending || lists.isPending || !quantityOk}>
          {pending ? text.adding : text.submit}
        </Button>
      </DialogFooter>
    </form>
  )
}

/** Hộp thoại "Thêm vào danh sách": chọn danh sách có sẵn hoặc tạo mới, rồi đặt số lượng. */
export function AddToListDialog({ product, onOpenChange }: AddToListDialogProps) {
  return (
    <Dialog open={product !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{strings.dialogs.addToList.title}</DialogTitle>
          <DialogDescription>
            {product ? strings.dialogs.addToList.description(product.name) : ''}
          </DialogDescription>
        </DialogHeader>
        {product ? (
          <AddToListForm key={product.id} product={product} onClose={() => onOpenChange(false)} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
