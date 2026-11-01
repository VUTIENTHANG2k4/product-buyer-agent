import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { RequestBody, ResponseBody, Schemas } from '@/api/types'

export type AlertCreate = RequestBody<'/api/alerts', 'post'>
export type AlertView = ResponseBody<'/api/alerts', 'post', 201>
export type AlertsResponse = ResponseBody<'/api/alerts', 'get'>
export type AlertPatch = RequestBody<'/api/alerts/{alert_id}', 'patch'>
export type AlertTestResult = ResponseBody<'/api/alerts/{alert_id}/test', 'post'>
export type AlertStatus = Schemas['AlertStatus']

/** Danh sách cảnh báo, mới nhất trước; `status` lọc theo trạng thái (bỏ trống là tất cả). */
export function useAlerts(status: AlertStatus | null) {
  return useQuery({
    queryKey: queryKeys.alerts.list(status),
    queryFn: ({ signal }) =>
      apiFetch<AlertsResponse>(status ? `alerts?status=${status}` : 'alerts', { signal }),
    // Đổi bộ lọc không làm bảng nháy về skeleton: giữ danh sách cũ tới khi có danh sách mới.
    placeholderData: keepPreviousData,
  })
}

/** Tạo cảnh báo giá (201). 409 `DUPLICATE_ALERT` khi đã có cảnh báo đang hiệu lực cùng ngưỡng. */
export function useCreateAlert() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: AlertCreate) =>
      apiFetch<AlertView>('alerts', { method: 'POST', json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.alerts.all }),
  })
}

/** Đổi ngưỡng và/hoặc tạm dừng, bật lại (`status` chỉ nhận `active`/`paused`). */
export function useUpdateAlert(alertId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: AlertPatch) =>
      apiFetch<AlertView>(`alerts/${alertId}`, { method: 'PATCH', json: patch }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.alerts.all }),
  })
}

export function useDeleteAlert(alertId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<void>(`alerts/${alertId}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.alerts.all }),
  })
}

/** "Gửi thử": hiện máy chủ luôn trả `sent: false` kèm lý do (bộ gửi thuộc M9). */
export function useTestAlert(alertId: number) {
  return useMutation({
    mutationFn: () => apiFetch<AlertTestResult>(`alerts/${alertId}/test`, { method: 'POST' }),
  })
}
