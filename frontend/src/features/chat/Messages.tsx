import { Bot, User } from 'lucide-react'
import type { ReactNode } from 'react'
import { StaleBadge } from '@/components/common/badges'
import { SafeMarkdown } from '@/components/common/SafeMarkdown'
import { Button } from '@/components/ui/button'
import { LiveItemsTable } from '@/features/results/LiveItemsTable'
import { ResultsTable } from '@/features/results/ResultsTable'
import { formatDateTime } from '@/lib/format'
import { strings } from '@/lib/strings'
import type { FinalEvent } from './events'

export function UserMessage({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary">
        <User className="size-4" aria-hidden="true" />
        <span className="sr-only">{strings.chat.you}</span>
      </span>
      <p className="min-w-0 pt-0.5 break-words whitespace-pre-wrap">{children}</p>
    </div>
  )
}

export function AssistantMessage({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Bot className="size-4" aria-hidden="true" />
        <span className="sr-only">{strings.chat.agent}</span>
      </span>
      <div className="min-w-0 flex-1 space-y-3">{children}</div>
    </div>
  )
}

/** Agent hỏi lại (lượt kết thúc bằng `clarification`): câu hỏi nổi bật, người dùng trả lời ở ô nhập. */
export function ClarificationBubble({ question }: { question: string }) {
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
      <p className="mb-1 font-medium text-primary">{strings.chat.clarificationTitle}</p>
      <SafeMarkdown>{question}</SafeMarkdown>
    </div>
  )
}

interface FinalAnswerViewProps {
  final: FinalEvent
  /** Bấm một gợi ý tiếp theo thì gửi nó như tin nhắn mới. */
  onSuggestion?: (text: string) => void
  disabled?: boolean
}

/** Câu trả lời cuối: văn bản, mốc dữ liệu, gợi ý tiếp. Gồm bảng kết quả (tầng 1) và bảng tìm trực tiếp (tầng 2). */
export function FinalAnswerView({ final, onSuggestion, disabled = false }: FinalAnswerViewProps) {
  return (
    <div className="space-y-3">
      <SafeMarkdown>{final.text}</SafeMarkdown>
      <ResultsTable rows={final.table} />
      <LiveItemsTable items={final.live_items} />
      {final.data_as_of ? (
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{strings.chat.dataAsOf(formatDateTime(final.data_as_of))}</span>
          <StaleBadge at={final.data_as_of} />
        </p>
      ) : null}
      {final.suggestions.length > 0 && onSuggestion ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">{strings.chat.followUpTitle}:</span>
          {final.suggestions.map((suggestion) => (
            <Button
              key={suggestion}
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => onSuggestion(suggestion)}
            >
              {suggestion}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
