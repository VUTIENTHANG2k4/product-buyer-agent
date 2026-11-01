import { cn } from 'cn'
import type { ComponentProps } from 'react'

/**
 * Ô chọn gốc của trình duyệt, kiểu dáng như `Input`. Dùng cho form ngắn trong hộp thoại: bàn phím và
 * trình đọc màn hình hỗ trợ sẵn, trên điện thoại mở bộ chọn của hệ điều hành.
 */
function NativeSelect({ className, ...props }: ComponentProps<'select'>) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        'h-9 w-full rounded-md border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 dark:bg-input/30',
        className,
      )}
      {...props}
    />
  )
}

export { NativeSelect }
