import { useMutation, useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { RequestBody, ResponseBody } from '@/api/types'

export type ChatRequest = RequestBody<'/api/chat', 'post'>
export type ChatAccepted = ResponseBody<'/api/chat', 'post', 202>
export type ConversationsResponse = ResponseBody<'/api/conversations', 'get'>
export type MessagesResponse = ResponseBody<'/api/conversations/{conversation_id}/messages', 'get'>

/** Gửi tin nhắn (202: agent chạy nền). Tin đầu không có `conversation_id`. */
export function useSendMessage() {
  return useMutation({
    mutationFn: (body: ChatRequest) =>
      apiFetch<ChatAccepted>('chat', { method: 'POST', json: body }),
  })
}

export function useConversations(limit = 5) {
  return useQuery({
    queryKey: [...queryKeys.conversations.all, limit],
    queryFn: ({ signal }) =>
      apiFetch<ConversationsResponse>(`conversations?limit=${limit}`, { signal }),
  })
}

/**
 * Lịch sử một hội thoại. Chụp một lần khi mở trang (`staleTime: Infinity`) và bỏ khỏi cache khi
 * rời trang (`gcTime: 0`): các lượt mới trong phiên hiển thị từ luồng SSE, nên làm mới nền sẽ
 * làm trùng tin nhắn.
 */
export function useMessages(conversationId: number | null) {
  return useQuery({
    queryKey: queryKeys.conversations.messages(conversationId ?? 0),
    queryFn: ({ signal }) =>
      apiFetch<MessagesResponse>(`conversations/${conversationId}/messages`, { signal }),
    enabled: conversationId !== null,
    staleTime: Infinity,
    gcTime: 0,
    refetchOnReconnect: false,
  })
}
