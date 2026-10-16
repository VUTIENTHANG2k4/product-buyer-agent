import { CircleDot } from 'lucide-react'
import { Outlet } from 'react-router'
import { strings } from '@/lib/strings'
import { NavBar } from './NavBar'

export function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="inline-flex items-center gap-2 text-lg font-semibold text-primary">
            <CircleDot className="size-5" aria-hidden="true" />
            {strings.appName}
          </span>
          <NavBar />
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
