/**
 * Kiểu của API, sinh từ OpenAPI của backend (`make gen-api`, xem `types.gen.ts`). OpenAPI là
 * nguồn sự thật (docs/07): không viết tay kiểu trùng với backend, chỉ đặt tên gọn ở đây.
 */
import type { components, paths } from './types.gen'

export type { components, paths }

/** Mọi schema phản hồi/yêu cầu theo tên lớp Pydantic, ví dụ `Schemas['ProductSummary']`. */
export type Schemas = components['schemas']

/** Thân JSON của phản hồi thành công (mã `Status`) của `Method` tại `Path`. */
export type ResponseBody<
  Path extends keyof paths,
  Method extends keyof paths[Path],
  Status extends number = 200,
> = paths[Path][Method] extends {
  responses: { [S in Status]: { content: { 'application/json': infer Body } } }
}
  ? Body
  : never

/** Thân JSON của yêu cầu `Method` tại `Path`. */
export type RequestBody<
  Path extends keyof paths,
  Method extends keyof paths[Path],
> = paths[Path][Method] extends { requestBody: { content: { 'application/json': infer Body } } }
  ? Body
  : never

/** Mã lỗi trong thân lỗi chuẩn `{error: {code, message, details}}` (docs/07 §1–2). */
export type ApiErrorBody = Schemas['ErrorResponse']
