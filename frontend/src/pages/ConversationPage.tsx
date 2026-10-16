import { useParams } from 'react-router'
import { strings } from '@/lib/strings'
import { PlaceholderPage } from './PlaceholderPage'

export function ConversationPage() {
  const { conversationId } = useParams()
  return (
    <PlaceholderPage
      title={strings.pages.conversation.title}
      description={strings.pages.conversation.description + strings.idSuffix(conversationId)}
    />
  )
}
