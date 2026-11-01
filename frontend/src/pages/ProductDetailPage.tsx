import { ArrowLeft } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { QueryBoundary } from '@/components/common/QueryBoundary'
import { ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useProduct } from '@/features/catalog/api'
import { parsePositiveId } from '@/features/catalog/ids'
import { ProductDetailView } from '@/features/catalog/ProductDetailView'
import { strings } from '@/lib/strings'

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex gap-4">
        <Skeleton className="size-32" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-6 w-1/4" />
        </div>
      </div>
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  )
}

function ProductBody({ id }: { id: number }) {
  const product = useProduct(id)
  return (
    <>
      {/* Khi chưa có dữ liệu trang vẫn có đúng một h1; có dữ liệu thì tên sản phẩm là h1. */}
      {product.data ? null : <h1 className="sr-only">{strings.pages.product.title}</h1>}
      <QueryBoundary
        query={product}
        errorTitle={strings.product.loadError}
        skeleton={<DetailSkeleton />}
      >
        {(data) => <ProductDetailView key={data.product_id} product={data} />}
      </QueryBoundary>
    </>
  )
}

export function ProductDetailPage() {
  const { id: raw } = useParams()
  const id = parsePositiveId(raw)
  const navigate = useNavigate()
  const location = useLocation()
  // `key` là "default" khi trang là mục đầu tiên của lịch sử (mở thẳng đường dẫn): quay về trang chính.
  const goBack = () => void (location.key !== 'default' ? navigate(-1) : navigate('/'))

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={goBack} className="-ml-2">
        <ArrowLeft aria-hidden="true" />
        {strings.product.back}
      </Button>
      {id === null ? (
        <>
          <h1 className="sr-only">{strings.pages.product.title}</h1>
          <ErrorState title={strings.product.notFoundTitle} message={strings.product.invalidId} />
        </>
      ) : (
        <ProductBody id={id} />
      )}
    </div>
  )
}
