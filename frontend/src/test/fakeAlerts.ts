import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import type { Schemas } from '@/api/types'
import { server } from '@/mocks/server'

type Alert = Schemas['AlertView']

export interface FakeAlerts {
  /** Cảnh báo hiện có, mới nhất trước; test sửa trực tiếp được. */
  alerts: Alert[]
  /** Địa chỉ GET đã nhận (gồm query), vd. `"alerts?status=paused"`. */
  reads: string[]
  /** Các yêu cầu ghi đã nhận: `"PATCH alerts/1 {...}"`, `"DELETE alerts/1"`, `"POST alerts/1/test"`. */
  writes: string[]
  /** Gán thì mọi yêu cầu ghi trả lỗi này. */
  failWrites: { status: number; code: string; message: string } | null
  /** Phản hồi của "Gửi thử"; mặc định luôn `sent: false` kèm lý do như máy chủ thật. */
  testResult: Schemas['AlertTestResponse']
  /** Gán một Promise để giữ phản hồi của yêu cầu ghi cho tới khi nó hoàn tất. */
  hold: Promise<void> | null
}

const notFound = () =>
  HttpResponse.json(
    { error: { code: 'ALERT_NOT_FOUND', message: 'Không tìm thấy cảnh báo', details: {} } },
    { status: 404 },
  )

/** Máy chủ cảnh báo giá giả có trạng thái (GET lọc theo `status`, PATCH, DELETE, test) bằng MSW. */
export function installFakeAlerts(initial: Alert[]): FakeAlerts {
  const fake: FakeAlerts = {
    alerts: structuredClone(initial),
    reads: [],
    writes: [],
    failWrites: null,
    testResult: { sent: false, reason: 'Bộ gửi thông báo chưa được cấu hình.' },
    hold: null,
  }

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
    fake.alerts.find((alert) => alert.alert_id === Number(id))

  server.use(
    http.get(apiUrl('alerts'), ({ request }) => {
      const url = new URL(request.url)
      fake.reads.push(`alerts${url.search}`)
      const status = url.searchParams.get('status')
      return HttpResponse.json({
        items: fake.alerts.filter((alert) => status === null || alert.status === status),
      })
    }),
    http.patch(apiUrl('alerts/:id'), async ({ params, request }) => {
      const failed = await write('PATCH', `alerts/${String(params.id)}`, request.clone())
      if (failed) return failed
      const alert = find(params.id)
      if (!alert) return notFound()
      Object.assign(alert, await request.json())
      return HttpResponse.json(alert)
    }),
    http.delete(apiUrl('alerts/:id'), async ({ params, request }) => {
      const failed = await write('DELETE', `alerts/${String(params.id)}`, request)
      if (failed) return failed
      if (!find(params.id)) return notFound()
      fake.alerts = fake.alerts.filter((alert) => alert.alert_id !== Number(params.id))
      return new HttpResponse(null, { status: 204 })
    }),
    http.post(apiUrl('alerts/:id/test'), async ({ params, request }) => {
      const failed = await write('POST', `alerts/${String(params.id)}/test`, request)
      if (failed) return failed
      return find(params.id) ? HttpResponse.json(fake.testResult) : notFound()
    }),
  )
  return fake
}
