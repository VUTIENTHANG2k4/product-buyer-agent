import { Check, Link2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useHref } from 'react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { strings } from '@/lib/strings'

/** Thời gian (ms) giữ chữ "Đã sao chép" trên nút. */
export const COPIED_RESET_MS = 2000

type CopyState = 'idle' | 'copied' | 'failed'

/**
 * Chép URL tuyệt đối của trang danh sách vào clipboard (X3). App không có đăng nhập nên link mở
 * được với bất kỳ ai truy cập được app. Không có clipboard (ngoài secure context) hoặc bị từ chối
 * thì hiện ô chỉ đọc chứa URL, tự focus và chọn sẵn chữ để người dùng tự chép.
 */
export function CopyLinkButton({ listId }: { listId: number }) {
  const href = useHref(`/lists/${listId}`)
  const url = new URL(href, window.location.origin).toString()
  const [state, setState] = useState<CopyState>('idle')
  const timer = useRef<number | undefined>(undefined)
  const field = useRef<HTMLInputElement>(null)
  const text = strings.lists

  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    if (state === 'failed') field.current?.focus()
  }, [state])

  const copy = async () => {
    window.clearTimeout(timer.current)
    try {
      if (!navigator.clipboard) throw new Error('clipboard unavailable')
      await navigator.clipboard.writeText(url)
      setState('copied')
      timer.current = window.setTimeout(() => setState('idle'), COPIED_RESET_MS)
    } catch {
      setState('failed')
    }
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => void copy()}>
        {state === 'copied' ? <Check aria-hidden="true" /> : <Link2 aria-hidden="true" />}
        {state === 'copied' ? text.linkCopied : text.copyLink}
      </Button>
      <span aria-live="polite" className="sr-only">
        {state === 'copied' ? text.linkCopied : ''}
      </span>
      {state === 'failed' ? (
        <div className="basis-full space-y-1 text-sm">
          <p role="alert">{text.copyFailed}</p>
          <Input
            ref={field}
            readOnly
            value={url}
            aria-label={text.shareUrl}
            onFocus={(event) => event.currentTarget.select()}
          />
        </div>
      ) : null}
    </>
  )
}
