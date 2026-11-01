import { useEffect } from 'react'
import { strings } from './strings'

/** Đặt `document.title` thành "<tiêu đề> · Buyer Agent"; không có tiêu đề thì chỉ hiện tên ứng dụng. */
export function useDocumentTitle(title: string | undefined) {
  useEffect(() => {
    document.title = strings.documentTitle(title)
  }, [title])
}
