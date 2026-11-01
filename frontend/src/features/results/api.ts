import { useQueries, useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { ResponseBody } from '@/api/types'

export type Comparison = ResponseBody<'/api/compare', 'post'>
export type ProductFull = ResponseBody<'/api/products/{product_id}', 'get'>

/**
 * So sánh 2–5 sản phẩm. `POST /compare` không đổi dữ liệu nên dùng như truy vấn (có cache theo
 * danh sách id); `ids` rỗng thì không gọi (ngăn so sánh đang đóng).
 */
export function useCompare(ids: readonly number[]) {
  return useQuery({
    queryKey: queryKeys.compare(ids),
    queryFn: ({ signal }) =>
      apiFetch<Comparison>('compare', { method: 'POST', json: { product_ids: ids }, signal }),
    enabled: ids.length >= 2,
  })
}

/** Tải từng sản phẩm theo id (hội thoại mở lại chỉ lưu `product_ids`). Giữ nguyên thứ tự `ids`. */
export function useProductsByIds(ids: readonly number[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.products.detail(id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        apiFetch<ProductFull>(`products/${id}`, { signal }),
    })),
  })
}
