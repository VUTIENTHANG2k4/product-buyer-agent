import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { RequestBody, ResponseBody } from '@/api/types'
import { removeItemFromDetail, patchItemInDetail } from './optimistic'

export type ListsResponse = ResponseBody<'/api/lists', 'get'>
export type ShoppingListSummary = ListsResponse['items'][number]
export type ShoppingListDetail = ResponseBody<'/api/lists/{list_id}', 'get'>
export type ShoppingListItem = ShoppingListDetail['items'][number]
export type ItemCreate = RequestBody<'/api/lists/{list_id}/items', 'post'>
export type ItemPatch = RequestBody<'/api/lists/{list_id}/items/{item_id}', 'patch'>

export function useLists() {
  return useQuery({
    queryKey: queryKeys.lists.all,
    queryFn: ({ signal }) => apiFetch<ListsResponse>('lists', { signal }),
  })
}

export function useList(id: number | null) {
  return useQuery({
    queryKey: queryKeys.lists.detail(id ?? 0),
    queryFn: ({ signal }) => apiFetch<ShoppingListDetail>(`lists/${id}`, { signal }),
    enabled: id !== null,
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

export function useRenameList(listId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<ShoppingListSummary>(`lists/${listId}`, { method: 'PATCH', json: { name } }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.lists.all }),
  })
}

export function useDeleteList(listId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<void>(`lists/${listId}`, { method: 'DELETE' }),
    onSuccess: () => {
      client.removeQueries({ queryKey: queryKeys.lists.detail(listId) })
      return client.invalidateQueries({ queryKey: queryKeys.lists.all })
    },
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

interface Snapshot {
  previous: ShoppingListDetail | undefined
}

/**
 * Sửa một mục (số lượng, ghi chú, nơi mua ưu tiên) theo kiểu lạc quan: giao diện đổi ngay, lỗi thì
 * hoàn tác về bản trước đó; xong (thành công hay lỗi) đều tải lại từ máy chủ để lấy giá chính xác.
 */
export function useUpdateItem(listId: number) {
  const client = useQueryClient()
  const key = queryKeys.lists.detail(listId)
  return useMutation({
    mutationFn: ({ itemId, patch }: { itemId: number; patch: ItemPatch }) =>
      apiFetch<unknown>(`lists/${listId}/items/${itemId}`, { method: 'PATCH', json: patch }),
    onMutate: async ({ itemId, patch }): Promise<Snapshot> => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<ShoppingListDetail>(key)
      if (previous) client.setQueryData(key, patchItemInDetail(previous, itemId, patch))
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
    },
    onSettled: () => client.invalidateQueries({ queryKey: queryKeys.lists.all }),
  })
}

/** Xóa một mục theo kiểu lạc quan (cùng cách hoàn tác như `useUpdateItem`). */
export function useRemoveItem(listId: number) {
  const client = useQueryClient()
  const key = queryKeys.lists.detail(listId)
  return useMutation({
    mutationFn: (itemId: number) =>
      apiFetch<void>(`lists/${listId}/items/${itemId}`, { method: 'DELETE' }),
    onMutate: async (itemId): Promise<Snapshot> => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<ShoppingListDetail>(key)
      if (previous) client.setQueryData(key, removeItemFromDetail(previous, itemId))
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
    },
    onSettled: () => client.invalidateQueries({ queryKey: queryKeys.lists.all }),
  })
}
