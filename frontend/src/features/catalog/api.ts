import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { ResponseBody } from '@/api/types'

export type ProductListResponse = ResponseBody<'/api/products', 'get'>
export type ProductDetail = ResponseBody<'/api/products/{product_id}', 'get'>
export type PriceHistory = ResponseBody<'/api/products/{product_id}/price-history', 'get'>

/** Khoảng ngày chọn được cho biểu đồ lịch sử giá (API nhận 1..180). */
export const HISTORY_RANGES = [7, 30, 90] as const
export type HistoryRange = (typeof HISTORY_RANGES)[number]

export function useProduct(id: number | null) {
  return useQuery({
    queryKey: queryKeys.products.detail(id ?? 0),
    queryFn: ({ signal }) => apiFetch<ProductDetail>(`products/${id}`, { signal }),
    enabled: id !== null,
  })
}

export function usePriceHistory(id: number | null, days: HistoryRange) {
  return useQuery({
    queryKey: queryKeys.products.priceHistory(id ?? 0, days),
    queryFn: ({ signal }) =>
      apiFetch<PriceHistory>(`products/${id}/price-history?days=${days}`, { signal }),
    enabled: id !== null,
  })
}

/** Một sản phẩm đủ để biết tổng số và mốc thu thập cũ nhất (`total`, `data_as_of`, `stale`). */
export function useCatalogSummary() {
  return useQuery({
    queryKey: queryKeys.products.summary,
    queryFn: ({ signal }) => apiFetch<ProductListResponse>('products?page_size=1', { signal }),
  })
}
