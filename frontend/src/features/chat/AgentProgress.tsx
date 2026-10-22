import { Bot, Check, ChevronDown, ChevronUp, Circle, Loader2, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { strings } from '@/lib/strings'
import { cn } from '@/lib/utils'
import { isFinished, type AgentRunState, type ToolStep } from './agentRunReducer'

function StepIcon({ state }: { state: 'done' | 'current' | 'pending' }) {
  if (state === 'done') return <Check className="size-4 text-success" aria-hidden="true" />
  if (state === 'current') {
    return (
      <Loader2
        className="size-4 animate-spin text-primary motion-reduce:animate-none"
        aria-hidden="true"
      />
    )
  }
  return <Circle className="size-4 text-muted-foreground" aria-hidden="true" />
}

function ToolRow({ tool }: { tool: ToolStep }) {
  const Icon = tool.status === 'ok' ? Check : tool.status === 'failed' ? X : Loader2
  const color =
    tool.status === 'ok'
      ? 'text-success'
      : tool.status === 'failed'
        ? 'text-destructive'
        : 'text-primary'
  return (
    <li className="flex items-center gap-2 text-xs text-muted-foreground">
      <Icon
        className={cn(
          'size-3.5 shrink-0',
          color,
          tool.status === 'running' && 'animate-spin motion-reduce:animate-none',
        )}
        aria-hidden="true"
      />
      <span className="sr-only">{strings.chat.toolStatus[tool.status]}: </span>
      <span>{tool.summary || tool.argsSummary}</span>
      {tool.durationMs !== undefined ? (
        <span className="tabular-nums">· {strings.chat.toolDuration(tool.durationMs)}</span>
      ) : null}
    </li>
  )
}

/**
 * Kế hoạch và các bước của agent theo thời gian thực (docs/08 §3.2). Vùng `aria-live="polite"`
 * để trình đọc màn hình đọc từng bước mới. API không gắn bước kế hoạch với từng tool, nên một bước
 * được coi là xong khi số tool đã chạy xong vượt qua vị trí của nó (hoặc khi cả lượt đã xong).
 */
export function AgentProgress({ state }: { state: AgentRunState }) {
  const [open, setOpen] = useState(true)
  const finished = isFinished(state.phase)
  const completedTools = state.tools.filter((tool) => tool.status !== 'running').length
  const allDone = state.phase === 'done' || state.phase === 'clarification'
  const waiting = state.steps.length === 0 && !finished

  if (state.steps.length === 0 && state.tools.length === 0 && finished) return null

  return (
    <section aria-label={strings.chat.planTitle} className="rounded-lg border bg-card p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-medium">
          <Bot className="size-4 text-primary" aria-hidden="true" />
          {strings.chat.planTitle}
        </h2>
        <Button
          variant="ghost"
          size="xs"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
          {open ? strings.chat.collapse : strings.chat.expand}
        </Button>
      </div>
      <div aria-live="polite" className={cn('mt-2 space-y-2', !open && 'hidden')}>
        {waiting ? (
          <p className="flex items-center gap-2 text-muted-foreground">
            <Loader2
              className="size-4 animate-spin text-primary motion-reduce:animate-none"
              aria-hidden="true"
            />
            {strings.chat.analyzing}
          </p>
        ) : null}
        {state.steps.length > 0 ? (
          <ol className="space-y-1.5">
            {state.steps.map((step, index) => {
              const done = allDone || index < completedTools
              const current = !done && !finished && index === completedTools
              return (
                <li key={`${index}-${step}`} className="flex items-start gap-2">
                  <span className="mt-0.5">
                    <StepIcon state={done ? 'done' : current ? 'current' : 'pending'} />
                  </span>
                  <span>{step}</span>
                </li>
              )
            })}
          </ol>
        ) : null}
        {state.tools.length > 0 ? (
          <ul className="space-y-1 border-t pt-2">
            {state.tools.map((tool) => (
              <ToolRow key={tool.callId} tool={tool} />
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  )
}
