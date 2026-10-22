import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { ResponseBody } from '@/api/types'

export type ProductListResponse = ResponseBody<'/api/products', 'get'>

/** Một sản phẩm đủ để biết tổng số và mốc thu thập cũ nhất (`total`, `data_as_of`, `stale`). */
export function useCatalogSummary() {
  return useQuery({
    queryKey: queryKeys.products.summary,
    queryFn: ({ signal }) => apiFetch<ProductListResponse>('products?page_size=1', { signal }),
  })
}
