import { useState } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'
import { useDeleteAlert, useTestAlert, useUpdateAlert, type AlertView } from './api'

/** Nút đổi trạng thái theo trạng thái hiện tại: đang theo dõi → tạm dừng; còn lại → bật lại. */
function toggleOf(status: AlertView['status']) {
  const text = strings.alerts
  if (status === 'active') return { label: text.pause, next: 'paused' as const }
  if (status === 'paused') return { label: text.resume, next: 'active' as const }
  return { label: text.watchAgain, next: 'active' as const }
}

/**
 * Thao tác của một cảnh báo: tạm dừng/tiếp tục (PATCH), "Gửi thử" (hiện đúng `reason` máy chủ trả,
 * không giả vờ đã gửi) và xóa (luôn hỏi lại). Dùng chung cho dạng bảng và dạng thẻ.
 */
export function AlertActions({ alert }: { alert: AlertView }) {
  const text = strings.alerts
  const update = useUpdateAlert(alert.alert_id)
  const test = useTestAlert(alert.alert_id)
  const remove = useDeleteAlert(alert.alert_id)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toggle = toggleOf(alert.status)
  const busy = update.isPending || remove.isPending

  const testResult = test.data
  let testMessage: string | null = null
  if (testResult) {
    testMessage = testResult.sent
      ? text.testSent
      : testResult.reason
        ? text.testNotSent(testResult.reason)
        : text.testNotSentNoReason
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          aria-label={text.actionLabel(toggle.label, alert.product_name)}
          onClick={() => {
            setError(null)
            update.mutate({ status: toggle.next }, { onError: (e) => setError(errorMessage(e)) })
          }}
        >
          {toggle.label}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={test.isPending}
          aria-label={text.actionLabel(text.test, alert.product_name)}
          onClick={() => {
            setError(null)
            test.mutate(undefined, { onError: (e) => setError(errorMessage(e)) })
          }}
        >
          {test.isPending ? text.testing : text.test}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          aria-label={text.actionLabel(text.remove, alert.product_name)}
          onClick={() => setConfirming(true)}
        >
          {text.remove}
        </Button>
      </div>
      {testMessage ? (
        <p role="status" className="text-xs text-muted-foreground">
          {testMessage}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          <span className="font-medium">{text.actionError}: </span>
          {error}
        </p>
      ) : null}
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{text.deleteTitle(alert.product_name)}</AlertDialogTitle>
            <AlertDialogDescription>{text.deleteDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{strings.common.cancel}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={remove.isPending}
              onClick={(event) => {
                event.preventDefault()
                remove.mutate(undefined, {
                  onSuccess: () => setConfirming(false),
                  onError: (e) => {
                    setConfirming(false)
                    setError(errorMessage(e))
                  },
                })
              }}
            >
              {text.deleteConfirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
