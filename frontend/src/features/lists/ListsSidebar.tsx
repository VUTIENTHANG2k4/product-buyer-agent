import { useId, useState, type FormEvent } from 'react'
import { NavLink, useNavigate } from 'react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { cn } from '@/lib/utils'
import { useCreateList, type ShoppingListSummary } from './api'
import { validateListName } from './listName'

function CreateListForm() {
  const navigate = useNavigate()
  const create = useCreateList()
  const id = useId()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const invalid = validateListName(name)
    if (invalid) {
      setError(invalid)
      return
    }
    setError(null)
    try {
      const created = await create.mutateAsync(name.trim())
      setName('')
      void navigate(`/lists/${created.list_id}`)
    } catch (failure) {
      setError(errorMessage(failure))
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <Label htmlFor={`${id}-name`}>{strings.lists.newListLabel}</Label>
      <Input
        id={`${id}-name`}
        value={name}
        placeholder={strings.lists.newListPlaceholder}
        aria-invalid={error !== null}
        onChange={(event) => setName(event.target.value)}
      />
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <Button type="submit" size="sm" disabled={create.isPending}>
        {create.isPending ? strings.lists.creating : strings.lists.createList}
      </Button>
    </form>
  )
}

interface ListsSidebarProps {
  lists: readonly ShoppingListSummary[]
  /** Danh sách đang mở (từ đường dẫn), nếu có. */
  currentId: number | null
}

/**
 * Chọn danh sách + tạo danh sách mới. Màn hình rộng (≥ 1024 px): cột liên kết bên trái;
 * hẹp: ô chọn ở trên cùng (docs/08 §3.5).
 */
export function ListsSidebar({ lists, currentId }: ListsSidebarProps) {
  const wide = useMediaQuery('(min-width: 1024px)')
  const navigate = useNavigate()
  const pickerId = useId()

  return (
    <aside aria-label={strings.lists.sidebarLabel} className="space-y-6">
      {lists.length > 0 ? (
        wide ? (
          <nav aria-label={strings.lists.sidebarLabel}>
            <ul className="space-y-1">
              {lists.map((list) => (
                <li key={list.list_id}>
                  <NavLink
                    to={`/lists/${list.list_id}`}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
                        isActive
                          ? 'bg-accent font-medium text-primary'
                          : 'hover:bg-muted text-foreground',
                      )
                    }
                  >
                    <span className="min-w-0 truncate">{list.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {strings.lists.itemsCount(list.item_count)}
                    </span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        ) : (
          <div className="space-y-1.5">
            <Label htmlFor={pickerId}>{strings.lists.pickerLabel}</Label>
            <NativeSelect
              id={pickerId}
              value={currentId ?? ''}
              onChange={(event) => void navigate(`/lists/${event.target.value}`)}
            >
              {currentId === null ? <option value="" /> : null}
              {lists.map((list) => (
                <option key={list.list_id} value={list.list_id}>
                  {list.name} ({strings.lists.itemsCount(list.item_count)})
                </option>
              ))}
            </NativeSelect>
          </div>
        )
      ) : null}
      <CreateListForm />
    </aside>
  )
}
