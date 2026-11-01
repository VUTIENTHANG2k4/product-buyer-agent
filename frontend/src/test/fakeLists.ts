import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import type { Schemas } from '@/api/types'
import { server } from '@/mocks/server'

type Detail = Schemas['ShoppingListDetail']

export interface FakeLists {
  /** Danh sách hiện có (chi tiết đầy đủ); test sửa trực tiếp được. */
  lists: Detail[]
  /** Các yêu cầu ghi đã nhận, theo thứ tự: `"PATCH lists/1/items/5 {...}"`. */
  writes: string[]
  /** Gán thì mọi yêu cầu ghi trả lỗi này (máy chủ từ chối). */
  failWrites: { status: number; code: string; message: string } | null
  /** Gán một Promise để giữ phản hồi của yêu cầu ghi cho tới khi nó hoàn tất (quan sát cập nhật lạc quan). */
  hold: Promise<void> | null
}

const summary = (list: Detail): Schemas['ShoppingListSummary'] => ({
  list_id: list.list_id,
  name: list.name,
  item_count: list.items.length,
  total_price: list.total_price,
  updated_at: list.updated_at,
})

const notFound = () =>
  HttpResponse.json(
    { error: { code: 'LIST_NOT_FOUND', message: 'Không tìm thấy danh sách', details: {} } },
    { status: 404 },
  )

function recompute(list: Detail) {
  list.item_count = list.items.length
  list.total_price = list.items.reduce(
    (sum, item) => sum + item.quantity * (item.current_price ?? 0),
    0,
  )
}

/** Dựng một máy chủ danh sách mua giả có trạng thái (GET/POST/PATCH/DELETE) bằng MSW. */
export function installFakeLists(initial: Detail[]): FakeLists {
  const fake: FakeLists = {
    lists: structuredClone(initial),
    writes: [],
    failWrites: null,
    hold: null,
  }
  let nextId = Math.max(0, ...initial.map((list) => list.list_id)) + 1

  async function write(method: string, path: string, request: Request) {
    const text = await request.text()
    fake.writes.push(`${method} ${path}${text ? ` ${text}` : ''}`)
    if (fake.hold) await fake.hold
    if (fake.failWrites) {
      const { status, code, message } = fake.failWrites
      return HttpResponse.json({ error: { code, message, details: {} } }, { status })
    }
    return null
  }

  const find = (id: string | readonly string[] | undefined) =>
    fake.lists.find((list) => list.list_id === Number(id))

  server.use(
    http.get(apiUrl('lists'), () => HttpResponse.json({ items: fake.lists.map(summary) })),
    http.post(apiUrl('lists'), async ({ request }) => {
      const failed = await write('POST', 'lists', request.clone())
      if (failed) return failed
      const body = (await request.json()) as { name: string }
      const created: Detail = {
        list_id: nextId++,
        name: body.name,
        item_count: 0,
        total_price: 0,
        updated_at: '2026-10-16T02:00:00Z',
        items: [],
      }
      fake.lists.unshift(created)
      return HttpResponse.json(summary(created), { status: 201 })
    }),
    http.get(apiUrl('lists/:id'), ({ params }) => {
      const list = find(params.id)
      return list ? HttpResponse.json(list) : notFound()
    }),
    http.patch(apiUrl('lists/:id'), async ({ params, request }) => {
      const failed = await write('PATCH', `lists/${String(params.id)}`, request.clone())
      if (failed) return failed
      const list = find(params.id)
      if (!list) return notFound()
      list.name = ((await request.json()) as { name: string }).name
      return HttpResponse.json(summary(list))
    }),
    http.delete(apiUrl('lists/:id'), async ({ params, request }) => {
      const failed = await write('DELETE', `lists/${String(params.id)}`, request)
      if (failed) return failed
      fake.lists = fake.lists.filter((list) => list.list_id !== Number(params.id))
      return new HttpResponse(null, { status: 204 })
    }),
    http.patch(apiUrl('lists/:id/items/:itemId'), async ({ params, request }) => {
      const failed = await write(
        'PATCH',
        `lists/${String(params.id)}/items/${String(params.itemId)}`,
        request.clone(),
      )
      if (failed) return failed
      const list = find(params.id)
      const item = list?.items.find((entry) => entry.item_id === Number(params.itemId))
      if (!list || !item) return notFound()
      Object.assign(item, await request.json())
      recompute(list)
      return HttpResponse.json(item)
    }),
    http.delete(apiUrl('lists/:id/items/:itemId'), async ({ params, request }) => {
      const failed = await write(
        'DELETE',
        `lists/${String(params.id)}/items/${String(params.itemId)}`,
        request,
      )
      if (failed) return failed
      const list = find(params.id)
      if (!list) return notFound()
      list.items = list.items.filter((entry) => entry.item_id !== Number(params.itemId))
      recompute(list)
      return new HttpResponse(null, { status: 204 })
    }),
  )
  return fake
}
