import { Bell, Bot, ListChecks, Settings, type LucideIcon } from 'lucide-react'
import { Link, matchPath, useLocation } from 'react-router'
import { useLists } from '@/features/lists/api'
import { cn } from '@/lib/utils'
import { strings } from '@/lib/strings'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Khớp đúng đường dẫn (mục không có route con); mặc định khớp cả tiền tố theo đoạn. */
  end?: boolean
  /** Đường dẫn khác cũng làm nổi mục này (hội thoại `/c/:id` thuộc luồng "Hỏi agent"). */
  alsoActiveFor?: string
}

export function NavBar() {
  const lists = useLists()
  const { pathname } = useLocation()
  // Tổng số mục trong mọi danh sách; chưa tải được hoặc chưa có mục nào thì không hiện số.
  const listCount = lists.data?.items.reduce((sum, list) => sum + list.item_count, 0) ?? 0

  const items: NavItem[] = [
    { to: '/', label: strings.nav.home, icon: Bot, end: true, alsoActiveFor: '/c/:conversationId' },
    {
      to: '/lists',
      label: listCount > 0 ? strings.nav.listsWithCount(listCount) : strings.nav.lists,
      icon: ListChecks,
      end: false,
    },
    { to: '/alerts', label: strings.nav.alerts, icon: Bell, end: true },
    { to: '/admin', label: strings.nav.admin, icon: Settings, end: true },
  ]

  return (
    <nav aria-label={strings.nav.label} className="flex flex-wrap items-center gap-1">
      {items.map(({ to, label, icon: Icon, end = false, alsoActiveFor }) => {
        const active =
          matchPath({ path: to, end }, pathname) !== null ||
          (alsoActiveFor !== undefined &&
            matchPath({ path: alsoActiveFor, end: true }, pathname) !== null)
        return (
          <Link
            key={to}
            to={to}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap',
              'outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
              active
                ? 'bg-accent text-primary'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            <Icon className="size-4" aria-hidden="true" />
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
