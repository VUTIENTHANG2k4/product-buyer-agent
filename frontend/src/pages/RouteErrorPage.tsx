import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { MAIN_CONTENT_ID } from '@/lib/a11y'
import { strings } from '@/lib/strings'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { PlaceholderPage } from './PlaceholderPage'

/** Màn hình lỗi khi một route bị lỗi lúc render: tiếng Việt, không hiện stack trace (08 §4). */
export function RouteErrorPage() {
  useDocumentTitle(strings.errors.pageTitle)
  return (
    <main id={MAIN_CONTENT_ID} className="mx-auto max-w-6xl space-y-4 px-4 py-6">
      <PlaceholderPage title={strings.errors.pageTitle} description={strings.errors.unknown} />
      <Button asChild variant="outline">
        <Link to="/" reloadDocument>
          {strings.notFoundBack}
        </Link>
      </Button>
    </main>
  )
}
