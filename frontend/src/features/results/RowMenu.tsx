import { MoreHorizontal } from 'lucide-react'
import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { strings } from '@/lib/strings'
import type { ProductRow } from './rows'

interface RowMenuProps {
  row: ProductRow
  onAddToList: (row: ProductRow) => void
  onCreateAlert: (row: ProductRow) => void
}

/** Menu `⋯` của một sản phẩm: xem chi tiết, thêm vào danh sách, báo khi giảm giá. */
export function RowMenu({ row, onAddToList, onCreateAlert }: RowMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={strings.results.rowMenu(row.name)}>
          <MoreHorizontal aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to={`/products/${row.product_id}`}>{strings.results.viewDetail}</Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onAddToList(row)}>
          {strings.results.addToList}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onCreateAlert(row)}>
          {strings.results.createAlert}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
