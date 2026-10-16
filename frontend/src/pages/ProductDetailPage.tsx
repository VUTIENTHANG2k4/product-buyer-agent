import { useParams } from 'react-router'
import { strings } from '@/lib/strings'
import { PlaceholderPage } from './PlaceholderPage'

export function ProductDetailPage() {
  const { id } = useParams()
  return (
    <PlaceholderPage
      title={strings.pages.product.title}
      description={strings.pages.product.description + strings.idSuffix(id)}
    />
  )
}
