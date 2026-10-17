import { CircleDot } from 'lucide-react'
import { useRef, type MouseEvent } from 'react'
import { Outlet, useMatches } from 'react-router'
import { MAIN_CONTENT_ID } from '@/lib/a11y'
import { titleFromMatches } from '@/lib/routeTitle'
import { strings } from '@/lib/strings'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { NavBar } from './NavBar'

export function AppLayout() {
  const mainRef = useRef<HTMLElement>(null)
  useDocumentTitle(titleFromMatches(useMatches()))

  // Chuyển focus bằng mã thay vì để trình duyệt nhảy theo #hash, để URL không bị thêm đoạn #main-content.
  const skipToContent = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    mainRef.current?.focus()
  }

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href={`#${MAIN_CONTENT_ID}`}
        onClick={skipToContent}
        className="sr-only rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground outline-hidden focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus-visible:ring-2 focus-visible:ring-ring"
      >
        {strings.skipToContent}
      </a>
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="inline-flex items-center gap-2 text-lg font-semibold text-primary">
            <CircleDot className="size-5" aria-hidden="true" />
            {strings.appName}
          </span>
          <NavBar />
        </div>
      </header>
      <main
        ref={mainRef}
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 outline-hidden"
      >
        <Outlet />
      </main>
    </div>
  )
}
