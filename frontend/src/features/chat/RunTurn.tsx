import { useEffect } from 'react'
import { ErrorState } from '@/components/common/states'
import { strings } from '@/lib/strings'
import { CONNECTION_LOST, isFinished } from './agentRunReducer'
import { AgentProgress } from './AgentProgress'
import { AssistantMessage, ClarificationBubble, FinalAnswerView, UserMessage } from './Messages'
import { useAgentRun } from './useAgentRun'

interface RunTurnProps {
  runId: string
  /** Tin nhắn người dùng của lượt; bỏ trống khi lịch sử đã hiển thị nó. */
  userText?: string
  /** Gửi lại một tin nhắn (nút "Hỏi lại" sau lỗi của agent, hoặc bấm gợi ý tiếp). */
  onAsk: (text: string) => void
  /**
   * Báo cho trang biết lượt đã kết thúc hay đang chạy lại (để mở/khóa ô nhập): `false` khi người dùng
   * bấm "Thử lại" sau mất kết nối và lượt quay về trạng thái đang kết nối.
   */
  onFinishedChange?: (runId: string, finished: boolean) => void
  /** Chặn các nút gửi tin nhắn mới (đang có lượt khác chạy). */
  busy?: boolean
}

/** Một lượt hỏi–đáp: tin người dùng, tiến trình agent, rồi câu trả lời / câu hỏi lại / lỗi. */
export function RunTurn({ runId, userText, onAsk, onFinishedChange, busy = false }: RunTurnProps) {
  const { state, reconnect } = useAgentRun(runId)
  const finished = isFinished(state.phase)

  useEffect(() => {
    onFinishedChange?.(runId, finished)
  }, [finished, onFinishedChange, runId])

  return (
    <div className="space-y-4">
      {userText ? <UserMessage>{userText}</UserMessage> : null}
      <AssistantMessage>
        <AgentProgress state={state} />
        {state.clarification ? <ClarificationBubble question={state.clarification} /> : null}
        {state.final ? (
          <FinalAnswerView final={state.final} onSuggestion={onAsk} disabled={busy} />
        ) : null}
        {state.error ? (
          state.error.code === CONNECTION_LOST ? (
            <ErrorState message={state.error.message} onRetry={reconnect} />
          ) : (
            <ErrorState
              message={state.error.message}
              onRetry={userText ? () => onAsk(userText) : undefined}
              retryLabel={strings.chat.ask}
            />
          )
        ) : null}
      </AssistantMessage>
    </div>
  )
}
