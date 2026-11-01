import { useId, useState, type FormEvent } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'
import { useDeleteList, useRenameList } from './api'
import { validateListName } from './listName'

function RenameForm({
  listId,
  currentName,
  onClose,
}: {
  listId: number
  currentName: string
  onClose: () => void
}) {
  const rename = useRenameList(listId)
  const id = useId()
  const [name, setName] = useState(currentName)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const invalid = validateListName(name)
    if (invalid) {
      setError(invalid)
      return
    }
    try {
      await rename.mutateAsync(name.trim())
      onClose()
    } catch (failure) {
      setError(errorMessage(failure))
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-name`}>{strings.lists.renameLabel}</Label>
        <Input
          id={`${id}-name`}
          value={name}
          aria-invalid={error !== null}
          onChange={(event) => setName(event.target.value)}
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
        <Button type="submit" disabled={rename.isPending}>
          {strings.common.save}
        </Button>
      </DialogFooter>
    </form>
  )
}

interface RenameListDialogProps {
  listId: number
  currentName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RenameListDialog({
  listId,
  currentName,
  open,
  onOpenChange,
}: RenameListDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{strings.lists.renameTitle}</DialogTitle>
        </DialogHeader>
        {open ? (
          <RenameForm
            listId={listId}
            currentName={currentName}
            onClose={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

interface DeleteListDialogProps {
  listId: number
  name: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Gọi sau khi xóa thành công (để rời trang danh sách đã xóa). */
  onDeleted: () => void
  onError: (message: string) => void
}

/** Xác nhận xóa danh sách: hành động không hoàn tác nên luôn hỏi trước. */
export function DeleteListDialog({
  listId,
  name,
  open,
  onOpenChange,
  onDeleted,
  onError,
}: DeleteListDialogProps) {
  const remove = useDeleteList(listId)
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{strings.lists.deleteTitle(name)}</AlertDialogTitle>
          <AlertDialogDescription>{strings.lists.deleteDescription}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{strings.common.cancel}</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={(event) => {
              event.preventDefault()
              remove.mutate(undefined, {
                onSuccess: () => {
                  onOpenChange(false)
                  onDeleted()
                },
                onError: (failure) => {
                  onOpenChange(false)
                  onError(errorMessage(failure))
                },
              })
            }}
            disabled={remove.isPending}
          >
            {strings.lists.deleteConfirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
