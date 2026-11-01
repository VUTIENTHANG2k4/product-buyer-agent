import { ImageOff } from 'lucide-react'
import { useState } from 'react'
import { safeUrl } from '@/lib/safeUrl'
import { cn } from '@/lib/utils'

/** Ảnh sản phẩm; thiếu, URL không phải http(s) hoặc tải lỗi thì hiện ô giữ chỗ. */
export function ProductImage({
  url,
  className,
}: {
  url: string | null | undefined
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  const src = url ? safeUrl(url) : ''
  if (!src || failed) {
    return (
      <span
        className={cn(
          'flex size-12 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground',
          className,
        )}
        aria-hidden="true"
      >
        <ImageOff className="size-5" />
      </span>
    )
  }
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={cn('size-12 shrink-0 rounded-md bg-muted object-contain', className)}
    />
  )
}
