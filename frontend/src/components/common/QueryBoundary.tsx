import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { strings } from '@/lib/strings'
import { EmptyState, ErrorState, LoadingBlock } from './states'

interface QueryBoundaryProps<T> {
  query: Pick<UseQueryResult<T>, 'data' | 'isPending' | 'isError' | 'error' | 'refetch'>
  /** Skeleton đúng hình dạng nội dung. */
  skeleton: ReactNode
  /** Bộ phận hiển thị khi dữ liệu rỗng; mặc định mọi dữ liệu đều "không rỗng". */
  isEmpty?: (data: T) => boolean
  empty?: ReactNode
  /** Tiêu đề hộp lỗi; mặc định "Không tải được dữ liệu". */
  errorTitle?: string
  children: (data: T) => ReactNode
}

/**
 * Gom bốn trạng thái của màn hình có dữ liệu (docs/08 §4): đang tải, lỗi, rỗng, có dữ liệu.
 * Nếu làm mới nền bị lỗi nhưng còn dữ liệu cũ thì vẫn hiện dữ liệu cũ.
 */
export function QueryBoundary<T>({
  query,
  skeleton,
  isEmpty,
  empty,
  errorTitle,
  children,
}: QueryBoundaryProps<T>) {
  if (query.data !== undefined) {
    if (isEmpty?.(query.data)) {
      return <>{empty ?? <EmptyState title={strings.common.emptyTitle} />}</>
    }
    return <>{children(query.data)}</>
  }
  if (query.isError) {
    return (
      <ErrorState error={query.error} title={errorTitle} onRetry={() => void query.refetch()} />
    )
  }
  return <LoadingBlock>{skeleton}</LoadingBlock>
}
