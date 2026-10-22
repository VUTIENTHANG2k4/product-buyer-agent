import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { RequestBody, ResponseBody } from '@/api/types'

export type ListsResponse = ResponseBody<'/api/lists', 'get'>
export type ShoppingListSummary = ListsResponse['items'][number]
export type ItemCreate = RequestBody<'/api/lists/{list_id}/items', 'post'>

export function useLists() {
  return useQuery({
    queryKey: queryKeys.lists.all,
    queryFn: ({ signal }) => apiFetch<ListsResponse>('lists', { signal }),
  })
}

/** Tạo danh sách mới (201). Làm mới mọi truy vấn `lists` để thanh điều hướng và trang danh sách cập nhật. */
export function useCreateList() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<ShoppingListSummary>('lists', { method: 'POST', json: { name } }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.lists.all }),
  })
}

/** Thêm sản phẩm vào danh sách (201); trùng thì máy chủ tăng số lượng. */
export function useAddListItem() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ listId, item }: { listId: number; item: ItemCreate }) =>
      apiFetch<unknown>(`lists/${listId}/items`, { method: 'POST', json: item }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.lists.all }),
  })
}
