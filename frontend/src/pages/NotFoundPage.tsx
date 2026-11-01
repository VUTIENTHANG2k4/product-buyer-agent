import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { strings } from '@/lib/strings'
import { PlaceholderPage } from './PlaceholderPage'

export function NotFoundPage() {
  return (
    <div className="space-y-4">
      <PlaceholderPage {...strings.pages.notFound} />
      <Button asChild variant="outline">
        <Link to="/">{strings.notFoundBack}</Link>
      </Button>
    </div>
  )
}
