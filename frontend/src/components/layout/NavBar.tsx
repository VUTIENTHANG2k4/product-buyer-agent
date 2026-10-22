import { Bell, Bot, ListChecks, Settings, type LucideIcon } from 'lucide-react'
import { NavLink } from 'react-router'
import { useLists } from '@/features/lists/api'
import { cn } from '@/lib/utils'
import { strings } from '@/lib/strings'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

export function NavBar() {
  const lists = useLists()
  // Tổng số mục trong mọi danh sách; chưa tải được hoặc chưa có mục nào thì không hiện số.
  const listCount = lists.data?.items.reduce((sum, list) => sum + list.item_count, 0) ?? 0

  const items: NavItem[] = [
    { to: '/', label: strings.nav.home, icon: Bot, end: true },
    {
      to: '/lists',
      label: listCount > 0 ? strings.nav.listsWithCount(listCount) : strings.nav.lists,
      icon: ListChecks,
    },
    { to: '/alerts', label: strings.nav.alerts, icon: Bell },
    { to: '/admin', label: strings.nav.admin, icon: Settings },
  ]

  return (
    <nav aria-label={strings.nav.label} className="flex flex-wrap items-center gap-1">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            cn(
              'inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap',
              'outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
              isActive
                ? 'bg-accent text-primary'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )
          }
        >
          <Icon className="size-4" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
