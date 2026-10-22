import { http, HttpResponse, type RequestHandler } from 'msw'
import { apiUrl } from '@/api/client'

/**
 * Handler dùng chung cho mọi test; handler theo màn hình thêm ở chính test đó (`server.use`).
 * Có sẵn các GET mà layout và trang chính luôn gọi (số mục danh sách mua, tóm tắt danh mục,
 * hội thoại gần đây) và lịch sử hội thoại rỗng, để test route không phải khai báo lại.
 */
export const handlers: RequestHandler[] = [
  http.get(apiUrl('lists'), () => HttpResponse.json({ items: [] })),
  http.get(apiUrl('products'), () =>
    HttpResponse.json({
      items: [],
      total: 0,
      page: 1,
      page_size: 1,
      stale: false,
      data_as_of: null,
    }),
  ),
  http.get(apiUrl('conversations'), () => HttpResponse.json({ items: [] })),
  http.get(apiUrl('conversations/:id/messages'), () => HttpResponse.json({ items: [] })),
]
