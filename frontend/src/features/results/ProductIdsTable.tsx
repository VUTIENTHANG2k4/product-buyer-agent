import { ErrorState, LoadingBlock } from '@/components/common/states'
import { Skeleton } from '@/components/ui/skeleton'
import { useProductsByIds } from './api'
import { ResultsTable } from './ResultsTable'
import { rowFromFull, type ProductRow } from './rows'

/**
 * Bảng của một câu trả lời cũ trong hội thoại mở lại: lịch sử chỉ lưu id nên tải từng sản phẩm
 * hiện tại (giá có thể đã đổi so với lúc hỏi). Sản phẩm không tải được thì bỏ qua; không tải được
 * sản phẩm nào thì báo lỗi.
 */
export function ProductIdsTable({ ids }: { ids: readonly number[] }) {
  const queries = useProductsByIds(ids)
  const rows: ProductRow[] = queries.flatMap((query) =>
    query.data ? [rowFromFull(query.data)] : [],
  )
  if (ids.length === 0) return null
  if (rows.length === 0) {
    const failed = queries.find((query) => query.isError)
    if (failed) {
      return (
        <ErrorState
          error={failed.error}
          onRetry={() => queries.forEach((query) => void query.refetch())}
        />
      )
    }
    return (
      <LoadingBlock>
        <Skeleton className="h-24 w-full" />
      </LoadingBlock>
    )
  }
  return <ResultsTable rows={rows} />
}
