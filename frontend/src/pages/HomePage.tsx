import { MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { StaleBadge } from '@/components/common/badges'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useCatalogSummary } from '@/features/catalog/api'
import { useConversations, useSendMessage } from '@/features/chat/api'
import { ChatComposer } from '@/features/chat/ChatComposer'
import { errorMessage } from '@/lib/errorMessage'
import { formatRelative } from '@/lib/format'
import { strings } from '@/lib/strings'

const SOURCES = [strings.sites.gearvn, strings.sites.fptshop, strings.sites.anphat].join(' · ')

function CatalogStatus() {
  const summary = useCatalogSummary()
  if (summary.isPending) return <Skeleton className="h-4 w-64" />
  // Lỗi tải thông tin phụ này không cần hộp lỗi: ô nhập vẫn dùng được; hộp lỗi hiện khi gửi tin.
  if (summary.isError) return null
  const { total, data_as_of: dataAsOf } = summary.data
  if (total === 0 || dataAsOf === null) {
    return (
      <p className="text-sm text-muted-foreground">
        {strings.chat.emptyCatalog}{' '}
        <Link to="/admin" className="text-primary underline underline-offset-2">
          {strings.nav.admin}
        </Link>
      </p>
    )
  }
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
      <span>
        {strings.chat.sources}: {SOURCES}
      </span>
      <span>{strings.chat.updated(formatRelative(dataAsOf))}</span>
      <StaleBadge at={dataAsOf} />
    </p>
  )
}

function RecentConversations() {
  const conversations = useConversations(5)
  const items = conversations.data?.items ?? []
  if (items.length === 0) return null
  return (
    <section aria-labelledby="recent-heading" className="space-y-2">
      <h2 id="recent-heading" className="text-sm font-medium text-muted-foreground">
        {strings.chat.recent}
      </h2>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.conversation_id}>
            <Link
              to={`/c/${item.conversation_id}`}
              className="inline-flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted"
            >
              <MessageSquare className="size-4 text-muted-foreground" aria-hidden="true" />
              {item.title || strings.chat.untitledConversation}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function HomePage() {
  const navigate = useNavigate()
  const send = useSendMessage()
  const [submitError, setSubmitError] = useState<string | null>(null)

  async function submit(message: string) {
    setSubmitError(null)
    try {
      const accepted = await send.mutateAsync({ message })
      void navigate(`/c/${accepted.conversation_id}?run=${encodeURIComponent(accepted.run_id)}`)
    } catch (error) {
      setSubmitError(errorMessage(error))
      throw error
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 py-6">
      <h1 className="text-center text-3xl font-semibold">{strings.pages.home.title}</h1>
      <ChatComposer onSend={submit} pending={send.isPending} error={submitError} />
      <div
        role="group"
        aria-label={strings.chat.suggestionsLabel}
        className="flex flex-wrap items-center gap-2"
      >
        <span className="text-sm text-muted-foreground">{strings.chat.suggestionsLabel}:</span>
        {strings.chat.suggestions.map((suggestion) => (
          <Button
            key={suggestion}
            variant="outline"
            size="sm"
            disabled={send.isPending}
            onClick={() => void submit(suggestion).catch(() => undefined)}
          >
            {suggestion}
          </Button>
        ))}
      </div>
      <CatalogStatus />
      <RecentConversations />
    </div>
  )
}
