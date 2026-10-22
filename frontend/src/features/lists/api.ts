import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { ResponseBody } from '@/api/types'

export type ListsResponse = ResponseBody<'/api/lists', 'get'>

export function useLists() {
  return useQuery({
    queryKey: queryKeys.lists.all,
    queryFn: ({ signal }) => apiFetch<ListsResponse>('lists', { signal }),
  })
}
