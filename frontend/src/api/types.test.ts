import { describe, expect, expectTypeOf, it } from 'vitest'

import openapi from '../../openapi.json'
import type { ApiErrorBody, RequestBody, ResponseBody, Schemas } from './types'

// Kiểu được kiểm lúc biên dịch (`tsc -b`); các `expect` bên dưới chỉ để vitest ghi nhận test.
describe('kiểu sinh từ OpenAPI', () => {
  it('có kiểu cho phản hồi và yêu cầu chính của API', () => {
    expectTypeOf<ResponseBody<'/api/chat', 'post', 202>>().toEqualTypeOf<Schemas['ChatAccepted']>()
    expectTypeOf<RequestBody<'/api/chat', 'post'>>().toEqualTypeOf<Schemas['ChatRequest']>()
    expectTypeOf<ResponseBody<'/api/products', 'get'>>().toEqualTypeOf<
      Schemas['ProductListResponse']
    >()
    expectTypeOf<RequestBody<'/api/compare', 'post'>>().toEqualTypeOf<Schemas['CompareRequest']>()
    expect(openapi.paths['/api/chat']).toBeDefined()
  })

  it('giữ nguyên tiền là số nguyên và id là số', () => {
    expectTypeOf<Schemas['ProductSummary']['min_price']>().toEqualTypeOf<number>()
    expectTypeOf<Schemas['ProductSummary']['product_id']>().toEqualTypeOf<number>()
    expectTypeOf<Schemas['AlertCreate']['target_price']>().toEqualTypeOf<number>()
    expect(openapi.components.schemas.ProductSummary.properties.min_price.type).toBe('integer')
  })

  it('có thân lỗi chuẩn với details là object', () => {
    expectTypeOf<ApiErrorBody['error']['code']>().toEqualTypeOf<string>()
    expectTypeOf<ApiErrorBody['error']['details']>().toEqualTypeOf<Record<string, unknown>>()
    expect(Object.keys(openapi.components.schemas)).not.toContain('HTTPValidationError')
  })

  it('mô tả sự kiện SSE bằng schema riêng để client dựng kiểu sự kiện', () => {
    expectTypeOf<Schemas['FinalEvent']['table']>().toEqualTypeOf<Schemas['ProductRow'][]>()
    expect(openapi.paths['/api/chat/{run_id}/events'].get.responses['200'].content).toHaveProperty(
      'text/event-stream',
    )
  })
})
