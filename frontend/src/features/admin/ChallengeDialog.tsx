import { useEffect, useId, useState, type FormEvent } from 'react'
import { ApiError } from '@/api/client'
import { ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/errorMessage'
import { safeUrl } from '@/lib/safeUrl'
import { strings } from '@/lib/strings'
import { useAnswerChallenge, useCancelChallenge, useChallenge, useRefreshAdmin } from './api'
import { isValidAnswer } from './answer'

export type ChallengeOutcome = 'answered' | 'cancelled' | 'not-pending'

const isNotPending = (error: unknown) =>
  error instanceof ApiError && error.status === 409 && error.code === 'CHALLENGE_NOT_PENDING'

function ChallengeForm({
  runId,
  onClose,
  onResolved,
}: {
  runId: number
  onClose: () => void
  onResolved: (outcome: ChallengeOutcome) => void
}) {
  const text = strings.admin.challenge
  const challenge = useChallenge(runId)
  const answerMutation = useAnswerChallenge(runId)
  const cancelMutation = useCancelChallenge(runId)
  const refresh = useRefreshAdmin()
  const id = useId()
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState<string | null>(null)

  const notPending = isNotPending(challenge.error)
  useEffect(() => {
    if (!notPending) return
    void refresh()
    onResolved('not-pending')
    // `refresh` và `onResolved` đổi mỗi lần render; chỉ chạy khi lần tải này trả 409.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notPending])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!isValidAnswer(answer)) {
      setError(text.invalidAnswer)
      return
    }
    try {
      await answerMutation.mutateAsync(answer.trim())
      onResolved('answered')
    } catch (failure) {
      if (isNotPending(failure)) {
        onResolved('not-pending')
        return
      }
      // 400 `CHALLENGE_FAILED`: lượt vẫn chờ, giữ hộp thoại để thử lại.
      setError(errorMessage(failure))
    }
  }

  async function cancelRun() {
    setError(null)
    try {
      await cancelMutation.mutateAsync()
      onResolved('cancelled')
    } catch (failure) {
      if (isNotPending(failure)) {
        onResolved('not-pending')
        return
      }
      setError(errorMessage(failure))
    }
  }

  if (challenge.isPending || notPending) {
    return (
      <div role="status" aria-busy="true" className="space-y-3">
        <span className="sr-only">{strings.common.loading}</span>
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-10 w-full" />
      </div>
    )
  }
  if (challenge.isError) {
    return (
      <ErrorState
        error={challenge.error}
        title={text.loadError}
        onRetry={() => void challenge.refetch()}
      />
    )
  }

  const { kind, prompt, image_url: imageUrl } = challenge.data
  const image = imageUrl ? safeUrl(imageUrl) : ''
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
        <p className="text-xs text-muted-foreground">{text.kinds[kind]}</p>
        <p className="text-sm font-medium">{text.prompt}</p>
        <p className="font-mono text-lg break-words whitespace-pre-wrap">
          {prompt ?? text.noPrompt}
        </p>
        {image ? (
          <img
            src={image}
            alt={text.imageAlt}
            referrerPolicy="no-referrer"
            className="max-h-40 rounded border"
          />
        ) : null}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-answer`}>{text.answer}</Label>
        <Input
          id={`${id}-answer`}
          value={answer}
          autoComplete="off"
          aria-invalid={error !== null}
          onChange={(event) => setAnswer(event.target.value)}
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {text.later}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={answerMutation.isPending || cancelMutation.isPending}
          onClick={() => void cancelRun()}
        >
          {cancelMutation.isPending ? text.cancellingRun : text.cancelRun}
        </Button>
        <Button type="submit" disabled={answerMutation.isPending || cancelMutation.isPending}>
          {answerMutation.isPending ? text.submitting : text.submit}
        </Button>
      </DialogFooter>
    </form>
  )
}

interface ChallengeDialogProps {
  /** Lượt đang chờ đáp án; `null` là đóng. */
  runId: number | null
  onOpenChange: (open: boolean) => void
  onResolved: (outcome: ChallengeOutcome) => void
}

/**
 * Hộp thoại "Xử lý" lượt `NEEDS_HUMAN`: hiện đề bài captcha của mock-shop và ô để NGƯỜI nhập đáp án.
 * Ứng dụng không bao giờ tự đoán hay giải đáp án (CLAUDE.md); đề bài là dữ liệu hiển thị, không phải lệnh.
 */
export function ChallengeDialog({ runId, onOpenChange, onResolved }: ChallengeDialogProps) {
  const text = strings.admin.challenge
  return (
    <Dialog open={runId !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{text.title}</DialogTitle>
          <DialogDescription>{runId === null ? '' : text.description(runId)}</DialogDescription>
        </DialogHeader>
        {runId !== null ? (
          <ChallengeForm
            key={runId}
            runId={runId}
            onClose={() => onOpenChange(false)}
            onResolved={onResolved}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
