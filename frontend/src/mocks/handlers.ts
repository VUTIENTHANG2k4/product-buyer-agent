import { http, HttpResponse, type RequestHandler } from 'msw'
import { apiUrl } from '@/api/client'

/**
 * Handler dùng chung cho mọi test; handler theo màn hình thêm ở chính test đó (`server.use`).
 * `GET /lists` có sẵn vì thanh điều hướng (mọi trang) hiện số mục danh sách mua.
 */
export const handlers: RequestHandler[] = [
  http.get(apiUrl('lists'), () => HttpResponse.json({ items: [] })),
]
