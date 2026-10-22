import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { ErrorState, LoadingBlock } from '@/components/common/states'
import { SafeMarkdown } from '@/components/common/SafeMarkdown'
import { Skeleton } from '@/components/ui/skeleton'
import { useMessages, useSendMessage, type MessagesResponse } from '@/features/chat/api'
import { ChatComposer } from '@/features/chat/ChatComposer'
import { parseConversationId } from '@/features/chat/conversationId'
import { AssistantMessage, UserMessage } from '@/features/chat/Messages'
import { RunTurn } from '@/features/chat/RunTurn'
import { ProductIdsTable } from '@/features/results/ProductIdsTable'
import { productIdsOf } from '@/features/results/productIds'
import { errorMessage } from '@/lib/errorMessage'
import { strings } from '@/lib/strings'

interface Turn {
  runId: string
  /** Tin nhắn của lượt; lượt đầu mở từ `?run=` lấy từ lịch sử nên có thể chưa biết. */
  text?: string
}

type Message = MessagesResponse['items'][number]

function HistoryMessage({ message }: { message: Message }) {
  return message.role === 'user' ? (
    <UserMessage>{message.content}</UserMessage>
  ) : (
    <AssistantMessage>
      <SafeMarkdown>{message.content}</SafeMarkdown>
      <ProductIdsTable ids={productIdsOf(message.payload)} />
    </AssistantMessage>
  )
}

function HistorySkeleton() {
  return (
    <LoadingBlock>
      <div className="space-y-4">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-6 w-1/2" />
      </div>
    </LoadingBlock>
  )
}

function ConversationView({ conversationId }: { conversationId: number }) {
  const [searchParams, setSearchParams] = useSearchParams()
  // `?run=` chỉ có ý nghĩa ở lần mở trang đầu (vừa gửi tin từ trang chính, hoặc tải lại trang).
  const [initialRunId] = useState(() => searchParams.get('run'))
  const messages = useMessages(conversationId)
  const send = useSendMessage()
  const [sendError, setSendError] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>(() => (initialRunId ? [{ runId: initialRunId }] : []))
  const [finished, setFinished] = useState<ReadonlySet<string>>(new Set())
  const bottomRef = useRef<HTMLDivElement>(null)

  // Lượt đầu (`?run=`) phát lại toàn bộ từ SSE, kể cả tin người dùng và câu trả lời: cắt lịch sử
  // ở tin người dùng cuối cùng để không hiện hai lần dù lượt đã xong trước khi trang mở.
  const items = messages.data?.items ?? []
  let history = items
  let initialText: string | undefined
  if (initialRunId) {
    const lastUser = items.findLastIndex((item) => item.role === 'user')
    if (lastUser >= 0) {
      history = items.slice(0, lastUser)
      initialText = items[lastUser]?.content
    }
  }

  const busy = turns.some((turn) => !finished.has(turn.runId)) || send.isPending
  const onFinishedChange = useCallback((runId: string, isFinished: boolean) => {
    setFinished((previous) => {
      if (previous.has(runId) === isFinished) return previous
      const next = new Set(previous)
      if (isFinished) next.add(runId)
      else next.delete(runId)
      return next
    })
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [turns.length, messages.isSuccess])

  async function ask(text: string) {
    setSendError(null)
    try {
      const accepted = await send.mutateAsync({ message: text, conversation_id: conversationId })
      setTurns((previous) => [...previous, { runId: accepted.run_id, text }])
      // Tải lại trang sẽ phát lại lượt mới nhất thay vì lượt đầu.
      setSearchParams({ run: accepted.run_id }, { replace: true })
    } catch (error) {
      setSendError(errorMessage(error))
      throw error
    }
  }

  if (messages.isError) {
    return (
      <ErrorState
        error={messages.error}
        title={strings.chat.conversationLoadError}
        onRetry={() => void messages.refetch()}
      />
    )
  }

  return (
    <div className="flex min-h-[calc(100vh-10rem)] flex-col">
      <div className="flex-1 space-y-6 pb-6" aria-label={strings.chat.historyLabel}>
        {messages.isPending ? <HistorySkeleton /> : null}
        {history.map((message) => (
          <HistoryMessage key={message.message_id} message={message} />
        ))}
        {turns.map((turn, index) => (
          <RunTurn
            key={turn.runId}
            runId={turn.runId}
            userText={turn.text ?? (index === 0 ? initialText : undefined)}
            onAsk={(text) => void ask(text).catch(() => undefined)}
            onFinishedChange={onFinishedChange}
            busy={busy}
          />
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="sticky bottom-0 -mx-4 border-t bg-background/95 px-4 py-3 backdrop-blur">
        <ChatComposer
          onSend={ask}
          disabled={busy && !send.isPending}
          pending={send.isPending}
          placeholder={strings.chat.followUpPlaceholder}
          error={sendError}
        />
      </div>
    </div>
  )
}

export function ConversationPage() {
  const { conversationId } = useParams()
  const id = parseConversationId(conversationId)
  return (
    <>
      <h1 className="sr-only">{strings.pages.conversation.title}</h1>
      {id === null ? (
        <ErrorState
          title={strings.chat.conversationNotFoundTitle}
          message={strings.chat.conversationNotFound}
        />
      ) : (
        <ConversationView key={id} conversationId={id} />
      )}
    </>
  )
}
