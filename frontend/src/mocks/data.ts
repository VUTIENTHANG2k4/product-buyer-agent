import type { Schemas } from '@/api/types'

/**
 * Nhà máy dữ liệu hư cấu cho test và ảnh chụp (tên có chữ "Mock", URL `.example`):
 * mỗi hàm trả một đối tượng hợp lệ theo schema OpenAPI, `overrides` ghi đè từng trường.
 */

export const MOCK_NOW = '2026-10-16T02:00:00Z'

export function rowOffer(overrides: Partial<Schemas['RowOffer']> = {}): Schemas['RowOffer'] {
  return {
    site: 'mockshop',
    price: 27_490_000,
    price_type: 'sale',
    stock_status: 'in_stock',
    url: 'https://mock-shop.example/p/mg15-4060',
    scraped_at: MOCK_NOW,
    ...overrides,
  }
}

export function productRow(overrides: Partial<Schemas['ProductRow']> = {}): Schemas['ProductRow'] {
  return {
    product_id: 12,
    name: 'MockBook Gaming 15 MG15-4060',
    brand: 'MockBrand',
    category: 'laptop',
    key_specs: { cpu_model: 'i7-13620H', gpu_model: 'RTX 4060', ram_gb: 16 },
    min_price: 27_490_000,
    offers: [rowOffer()],
    image_url: null,
    ...overrides,
  }
}

export function offerView(overrides: Partial<Schemas['OfferView']> = {}): Schemas['OfferView'] {
  return {
    offer_id: 101,
    site: 'mockshop',
    title: 'MockBook Gaming 15 MG15-4060',
    url: 'https://mock-shop.example/p/mg15-4060',
    price: 27_490_000,
    list_price: 29_990_000,
    effective_price: 27_490_000,
    price_type: 'sale',
    stock_status: 'in_stock',
    rating: null,
    scraped_at: MOCK_NOW,
    ...overrides,
  }
}

export function productFull(
  overrides: Partial<Schemas['ProductFull']> = {},
): Schemas['ProductFull'] {
  return {
    product_id: 12,
    name: 'MockBook Gaming 15 MG15-4060',
    brand: 'MockBrand',
    category: 'laptop',
    model_code: 'MG15-4060',
    specs: { cpu_model: 'i7-13620H', gpu_model: 'RTX 4060', ram_gb: 16 },
    specs_confidence: 1,
    image_url: null,
    offers: [offerView()],
    min_price: 27_490_000,
    max_price: 27_490_000,
    ...overrides,
  }
}

export function listSummary(
  overrides: Partial<Schemas['ShoppingListSummary']> = {},
): Schemas['ShoppingListSummary'] {
  return {
    list_id: 1,
    name: 'Mock danh sách laptop',
    item_count: 2,
    total_price: 55_000_000,
    updated_at: MOCK_NOW,
    ...overrides,
  }
}

export function listItem(
  overrides: Partial<Schemas['ShoppingListItemView']> = {},
): Schemas['ShoppingListItemView'] {
  return {
    item_id: 1,
    product_id: 12,
    name: 'MockBook Gaming 15 MG15-4060',
    quantity: 1,
    note: null,
    preferred_offer_id: null,
    price_at_add: 27_990_000,
    current_price: 27_490_000,
    price_delta: -500_000,
    best_offer: offerView(),
    ...overrides,
  }
}

export function listDetail(
  overrides: Partial<Schemas['ShoppingListDetail']> = {},
): Schemas['ShoppingListDetail'] {
  const items = overrides.items ?? [listItem()]
  return {
    list_id: 1,
    name: 'Mock danh sách laptop',
    item_count: items.length,
    total_price: items.reduce((sum, item) => sum + item.quantity * (item.current_price ?? 0), 0),
    updated_at: MOCK_NOW,
    items,
    ...overrides,
  }
}

export function alertView(overrides: Partial<Schemas['AlertView']> = {}): Schemas['AlertView'] {
  return {
    alert_id: 1,
    product_id: 12,
    product_name: 'MockBook Gaming 15 MG15-4060',
    target_price: 26_000_000,
    channel: 'email',
    destination: 'mock@example.com',
    status: 'active',
    current_best_price: 27_490_000,
    last_notified_price: null,
    last_notified_at: null,
    created_at: MOCK_NOW,
    ...overrides,
  }
}
