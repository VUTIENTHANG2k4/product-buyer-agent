import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { apiUrl } from '@/api/client'
import { listDetail, listItem } from '@/mocks/data'
import { server } from '@/mocks/server'
import { installFakeLists } from '@/test/fakeLists'
import { createTestQueryClient } from '@/test/renderWithProviders'
import { useList, useRemoveItem, useUpdateItem } from './api'
import { patchItemInDetail, removeItemFromDetail, totalOf } from './optimistic'

const item = (id: number, quantity: number, price: number | null) =>
  listItem({ item_id: id, quantity, current_price: price })

describe('totalOf / patchItemInDetail · biên (QA M8)', () => {
  it('giá 5 tỷ × 10.000 chiếc vẫn là số nguyên an toàn (5 × 10^13)', () => {
    expect(totalOf([item(1, 10_000, 5_000_000_000)])).toBe(50_000_000_000_000)
    expect(Number.isSafeInteger(totalOf([item(1, 10_000, 5_000_000_000)]))).toBe(true)
  })

  it('giá hiện tại 0 đóng góp 0, khác với giá null chỉ là không tính', () => {
    expect(totalOf([item(1, 3, 0), item(2, 2, 100)])).toBe(200)
  })

  it('bản vá số lượng 0 hoặc âm được áp nguyên (lớp lạc quan không tự kiểm; giao diện đã chặn trước)', () => {
    const detail = listDetail({ items: [item(1, 2, 100)] })
    expect(patchItemInDetail(detail, 1, { quantity: 0 }).total_price).toBe(0)
    expect(patchItemInDetail(detail, 1, { quantity: -2 }).total_price).toBe(-200)
  })

  it('bản vá rỗng {} không đổi mục nào nhưng tổng vẫn tính lại từ các mục', () => {
    const detail = listDetail({ items: [item(1, 2, 100)], total_price: 999 })
    const next = patchItemInDetail(detail, 1, {})
    expect(next.items).toEqual(detail.items)
    expect(next.total_price).toBe(200)
  })

  it('xóa mục cuối cùng: 0 mục, tổng 0', () => {
    const detail = listDetail({ items: [item(1, 2, 100)] })
    const next = removeItemFromDetail(detail, 1)
    expect(next.items).toEqual([])
    expect(next.item_count).toBe(0)
    expect(next.total_price).toBe(0)
  })

  it('bản vá trên danh sách rỗng không ném lỗi', () => {
    const detail = listDetail({ items: [] })
    expect(patchItemInDetail(detail, 5, { quantity: 3 }).items).toEqual([])
  })
})

function harness() {
  const client = createTestQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(
    () => ({
      list: useList(1),
      update: useUpdateItem(1),
      remove: useRemoveItem(1),
    }),
    { wrapper },
  )
}

const quantityOf = (result: ReturnType<typeof harness>['result'], itemId: number) =>
  result.current.list.data?.items.find((entry) => entry.item_id === itemId)?.quantity

describe('cập nhật lạc quan · chồng chéo và lỗi (QA M8)', () => {
  it('hai cập nhật số lượng liên tiếp, cả hai thành công: kết quả cuối là giá trị sau cùng', async () => {
    const fake = installFakeLists([listDetail({ items: [item(1, 1, 100)] })])
    const { result } = harness()
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true))

    act(() => {
      result.current.update.mutate({ itemId: 1, patch: { quantity: 2 } })
      result.current.update.mutate({ itemId: 1, patch: { quantity: 3 } })
    })
    await waitFor(() => expect(fake.writes).toHaveLength(2))
    await waitFor(() => expect(quantityOf(result, 1)).toBe(3))
    await waitFor(() => expect(result.current.update.isPending).toBe(false))
    expect(fake.lists[0]?.items[0]?.quantity).toBe(3)
  })

  it('cập nhật đầu lỗi, cập nhật sau thành công: sau khi tải lại, giao diện khớp máy chủ (3)', async () => {
    const calls: number[] = []
    const state = { quantity: 1 }
    server.use(
      http.get(apiUrl('lists/1'), () =>
        HttpResponse.json(listDetail({ items: [item(1, state.quantity, 100)] })),
      ),
      http.patch(apiUrl('lists/1/items/1'), async ({ request }) => {
        const body = (await request.json()) as { quantity: number }
        calls.push(body.quantity)
        if (body.quantity === 2) {
          await new Promise((resolve) => setTimeout(resolve, 60))
          return HttpResponse.json(
            { error: { code: 'INTERNAL_ERROR', message: 'lỗi', details: {} } },
            { status: 500 },
          )
        }
        state.quantity = body.quantity
        return HttpResponse.json({})
      }),
    )
    const { result } = harness()
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true))

    act(() => {
      result.current.update.mutate({ itemId: 1, patch: { quantity: 2 } })
    })
    await waitFor(() => expect(quantityOf(result, 1)).toBe(2))
    act(() => {
      result.current.update.mutate({ itemId: 1, patch: { quantity: 3 } })
    })
    await waitFor(() => expect(calls).toEqual([2, 3]))
    await waitFor(() => expect(quantityOf(result, 1)).toBe(3))
    // Đợi yêu cầu lỗi kết thúc và tải lại xong rồi mới kết luận (không còn gì đang bay).
    await new Promise((resolve) => setTimeout(resolve, 150))
    await waitFor(() => expect(result.current.list.isFetching).toBe(false))
    expect(quantityOf(result, 1)).toBe(3)
  })

  it('lỗi giữa chừng: giao diện hoàn tác về số cũ rồi khớp máy chủ', async () => {
    const fake = installFakeLists([listDetail({ items: [item(1, 4, 100)] })])
    const { result } = harness()
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true))

    fake.failWrites = { status: 500, code: 'INTERNAL_ERROR', message: 'Máy chủ gặp sự cố' }
    act(() => {
      result.current.update.mutate({ itemId: 1, patch: { quantity: 9 } })
    })
    await waitFor(() => expect(result.current.update.isError).toBe(true))
    await waitFor(() => expect(quantityOf(result, 1)).toBe(4))
    expect(result.current.list.data?.total_price).toBe(400)
  })

  it('xóa mục rồi sửa mục đã xóa (404): mục biến mất khỏi giao diện sau khi tải lại, không kẹt lạc quan', async () => {
    const fake = installFakeLists([listDetail({ items: [item(1, 1, 100), item(2, 1, 200)] })])
    const { result } = harness()
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true))

    act(() => {
      result.current.remove.mutate(1)
    })
    await waitFor(() => expect(fake.lists[0]?.items).toHaveLength(1))
    act(() => {
      result.current.update.mutate({ itemId: 1, patch: { quantity: 5 } })
    })
    await waitFor(() => expect(result.current.update.isError).toBe(true))
    await waitFor(() => expect(result.current.list.isFetching).toBe(false))
    expect(result.current.list.data?.items.map((entry) => entry.item_id)).toEqual([2])
    expect(result.current.list.data?.total_price).toBe(200)
  })
})
