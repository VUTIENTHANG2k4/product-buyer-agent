import { Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Price } from '@/components/common/badges'
import { QueryBoundary } from '@/components/common/QueryBoundary'
import { EmptyState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'
import { useList, useRemoveItem, useUpdateItem, type ShoppingListDetail } from './api'
import { DeleteListDialog, RenameListDialog } from './ListDialogs'
import { ListItemCard } from './ListItemCard'

function DetailBody({ list }: { list: ShoppingListDetail }) {
  const navigate = useNavigate()
  const update = useUpdateItem(list.list_id)
  const remove = useRemoveItem(list.list_id)
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const text = strings.lists

  const fail = (error: unknown) => setActionError(errorMessage(error))
  const hasUnavailable = list.items.some((item) => item.current_price === null)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold break-words">{list.name}</h2>
          <p className="text-sm text-muted-foreground">{text.itemsCount(list.item_count)}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setRenaming(true)}>
            <Pencil aria-hidden="true" />
            {text.rename}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setDeleting(true)}>
            <Trash2 aria-hidden="true" />
            {text.deleteList}
          </Button>
        </div>
      </div>

      {actionError ? (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"
        >
          <span className="font-medium">{text.actionError}: </span>
          {actionError}
        </p>
      ) : null}

      {list.items.length === 0 ? (
        <EmptyState
          title={text.emptyItemsTitle}
          description={text.emptyItemsHint}
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/">{text.askAgent}</Link>
            </Button>
          }
        />
      ) : (
        <ul aria-label={text.itemsTitle} className="space-y-3">
          {list.items.map((item) => (
            <ListItemCard
              key={item.item_id}
              item={item}
              onUpdate={(itemId, patch) => {
                setActionError(null)
                update.mutate({ itemId, patch }, { onError: fail })
              }}
              onRemove={(itemId) => {
                setActionError(null)
                remove.mutate(itemId, { onError: fail })
              }}
            />
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-lg border bg-card p-4">
        <span className="font-medium">{text.total}</span>
        <Price amount={list.total_price} className="text-xl font-semibold" />
      </div>
      {hasUnavailable ? <p className="text-xs text-muted-foreground">{text.totalNote}</p> : null}

      <RenameListDialog
        listId={list.list_id}
        currentName={list.name}
        open={renaming}
        onOpenChange={setRenaming}
      />
      <DeleteListDialog
        listId={list.list_id}
        name={list.name}
        open={deleting}
        onOpenChange={setDeleting}
        onDeleted={() => void navigate('/lists')}
        onError={(message) => setActionError(message)}
      />
    </div>
  )
}

/** Chi tiết một danh sách mua: các mục (sửa số lượng, ghi chú, nơi mua, xóa) và tổng tiền. */
export function ListDetail({ id }: { id: number }) {
  const list = useList(id)
  return (
    <QueryBoundary
      query={list}
      errorTitle={strings.lists.loadError}
      skeleton={
        <div className="space-y-3">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      }
    >
      {(data) => <DetailBody list={data} />}
    </QueryBoundary>
  )
}
