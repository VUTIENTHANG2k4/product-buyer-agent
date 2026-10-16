import { useParams } from 'react-router'
import { strings } from '@/lib/strings'
import { PlaceholderPage } from './PlaceholderPage'

/** Dùng cho cả `/lists` và `/lists/:id`. */
export function ListsPage() {
  const { id } = useParams()
  const page = id ? strings.pages.list : strings.pages.lists
  return (
    <PlaceholderPage title={page.title} description={page.description + strings.idSuffix(id)} />
  )
}
