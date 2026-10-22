import { SendHorizontal } from 'lucide-react'
import { useId, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { strings } from '@/lib/strings'

interface ChatComposerProps {
  /** Gửi tin nhắn đã cắt khoảng trắng. Ném lỗi thì giữ nguyên nội dung để người dùng thử lại. */
  onSend: (message: string) => Promise<unknown> | void
  disabled?: boolean
  pending?: boolean
  placeholder?: string
  /** Lỗi từ lần gửi trước, hiện ngay dưới ô nhập. */
  error?: string | null
}

const MAX = strings.chat.maxLength
const COUNTER_FROM = Math.floor(MAX * 0.9)

/** Ô nhập tin nhắn: Enter gửi, Shift+Enter xuống dòng (không gửi khi đang gõ dấu bằng bộ gõ IME). */
export function ChatComposer({
  onSend,
  disabled = false,
  pending = false,
  placeholder = strings.chat.composerPlaceholder,
  error = null,
}: ChatComposerProps) {
  const [value, setValue] = useState('')
  const id = useId()
  const hintId = `${id}-hint`
  const trimmed = value.trim()
  const tooLong = value.length > MAX
  const canSend = trimmed !== '' && !tooLong && !disabled && !pending

  async function submit() {
    if (!canSend) return
    try {
      await onSend(trimmed)
      setValue('')
    } catch {
      // Lỗi hiện ở nơi gọi (prop `error`); giữ nội dung để thử lại.
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void submit()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void submit()
    }
  }

  const hint = tooLong ? strings.chat.tooLong(MAX) : error
  return (
    <form onSubmit={handleSubmit} className="space-y-1.5">
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label htmlFor={id} className="sr-only">
            {strings.chat.composerLabel}
          </label>
          <Textarea
            id={id}
            value={value}
            rows={2}
            disabled={disabled}
            placeholder={placeholder}
            aria-invalid={tooLong || Boolean(error)}
            aria-describedby={hint || value.length >= COUNTER_FROM ? hintId : undefined}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
            className="min-h-14 resize-none"
          />
        </div>
        <Button type="submit" disabled={!canSend}>
          <SendHorizontal aria-hidden="true" />
          {pending ? strings.chat.sending : strings.chat.send}
        </Button>
      </div>
      <div id={hintId} className="flex justify-between gap-2 text-xs">
        <span role={hint ? 'alert' : undefined} className="text-destructive">
          {hint}
        </span>
        {value.length >= COUNTER_FROM ? (
          <span className={tooLong ? 'text-destructive' : 'text-muted-foreground'}>
            {strings.chat.counter(value.length, MAX)}
          </span>
        ) : null}
      </div>
    </form>
  )
}
