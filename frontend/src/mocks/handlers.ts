import type { RequestHandler } from 'msw'

/** Handler dùng chung cho mọi test; handler theo màn hình sẽ thêm ở M8. */
export const handlers: RequestHandler[] = []
