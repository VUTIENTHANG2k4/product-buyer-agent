import { Link, Navigate, useParams } from 'react-router'
import { ErrorState, EmptyState, LoadingBlock } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { parsePositiveId } from '@/features/catalog/ids'
import { useLists } from '@/features/lists/api'
import { ListDetail } from '@/features/lists/ListDetail'
import { ListsSidebar } from '@/features/lists/ListsSidebar'
import { strings } from '@/lib/strings'

/** Dùng cho cả `/lists` (mở danh sách đầu tiên) và `/lists/:id`. */
export function ListsPage() {
  const { id: raw } = useParams()
  const lists = useLists()
  const id = raw === undefined ? undefined : parsePositiveId(raw)
  const items = lists.data?.items ?? []

  let body
  if (lists.isPending) {
    body = (
      <LoadingBlock>
        <div className="space-y-3">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-32 w-full" />
        </div>
      </LoadingBlock>
    )
  } else if (lists.isError) {
    body = (
      <ErrorState
        error={lists.error}
        title={strings.lists.loadError}
        onRetry={() => void lists.refetch()}
      />
    )
  } else if (id === null) {
    body = <ErrorState title={strings.lists.notFoundTitle} message={strings.lists.invalidId} />
  } else if (id === undefined) {
    const first = items[0]
    body = first ? (
      <Navigate to={`/lists/${first.list_id}`} replace />
    ) : (
      <EmptyState
        title={strings.lists.emptyTitle}
        description={strings.lists.emptyHint}
        action={
          <Button asChild variant="outline" size="sm">
            <Link to="/">{strings.lists.askAgent}</Link>
          </Button>
        }
      />
    )
  } else {
    body = <ListDetail key={id} id={id} />
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{strings.pages.lists.title}</h1>
      <div className="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <ListsSidebar lists={items} currentId={typeof id === 'number' ? id : null} />
        <section aria-label={strings.lists.itemsTitle} className="min-w-0">
          {body}
        </section>
      </div>
    </div>
  )
}
