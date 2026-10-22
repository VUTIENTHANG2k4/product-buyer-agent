import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { RequestBody, ResponseBody } from '@/api/types'

export type AlertCreate = RequestBody<'/api/alerts', 'post'>
export type AlertView = ResponseBody<'/api/alerts', 'post', 201>

/** Tạo cảnh báo giá (201). 409 `DUPLICATE_ALERT` khi đã có cảnh báo đang hiệu lực cùng ngưỡng. */
export function useCreateAlert() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: AlertCreate) =>
      apiFetch<AlertView>('alerts', { method: 'POST', json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.alerts.all }),
  })
}
