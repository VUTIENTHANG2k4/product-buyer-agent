import type { Schemas } from '@/api/types'

export type ProductRow = Schemas['ProductRow']
export type RowOffer = Schemas['RowOffer']

export const MIN_COMPARE = 2
export const MAX_COMPARE = 5

export type SortKey = 'price' | 'name'
export type SortDir = 'asc' | 'desc'
export interface Sort {
  key: SortKey
  dir: SortDir
}

/** Chiều sắp xếp kế tiếp khi bấm tiêu đề cột: chưa sắp → tăng → giảm → bỏ sắp xếp. */
export function nextSort(current: Sort | null, key: SortKey): Sort | null {
  if (current?.key !== key) return { key, dir: 'asc' }
  return current.dir === 'asc' ? { key, dir: 'desc' } : null
}

/** Sắp xếp một bản sao; sản phẩm chưa có giá luôn xếp cuối dù tăng hay giảm. */
export function sortRows(rows: readonly ProductRow[], sort: Sort | null): ProductRow[] {
  if (!sort) return [...rows]
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    if (sort.key === 'name') return sign * a.name.localeCompare(b.name, 'vi')
    const pa = a.min_price ?? null
    const pb = b.min_price ?? null
    if (pa === null && pb === null) return 0
    if (pa === null) return 1
    if (pb === null) return -1
    return sign * (pa - pb)
  })
}

/** Offer rẻ nhất trong hàng (theo giá hiệu lực đã nằm trong `price`). */
export function cheapestOfferPrice(row: ProductRow): number | null {
  const prices = (row.offers ?? []).map((offer) => offer.price)
  return prices.length > 0 ? Math.min(...prices) : (row.min_price ?? null)
}

/** `ProductFull` (từ `GET /products/{id}`) về dạng hàng bảng, cho hội thoại mở lại chỉ có `product_ids`. */
export function rowFromFull(product: Schemas['ProductFull']): ProductRow {
  const offers: RowOffer[] = (product.offers ?? [])
    .map((offer) => ({
      site: offer.site,
      price: offer.effective_price,
      price_type: offer.price_type,
      stock_status: offer.stock_status,
      url: offer.url,
      scraped_at: offer.scraped_at,
    }))
    .sort((a, b) => a.price - b.price)
  return {
    product_id: product.product_id,
    name: product.name,
    brand: product.brand,
    category: product.category,
    key_specs: product.specs ?? {},
    min_price: product.min_price ?? offers[0]?.price ?? null,
    offers,
    image_url: product.image_url ?? null,
  }
}
