"""Danh mục sản phẩm đã thu thập: tìm, chi tiết, lịch sử giá, so sánh (docs/07 §3.3)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from pydantic import Field

from app.api.deps import CatalogServiceDep, CompareServiceDep
from app.api.errors import error_responses
from app.api.schemas import CompareRequest, ProductListResponse
from app.domain.catalog import CatalogFilters, Comparison, PriceHistoryResult, ProductFull
from app.domain.dto import INT8_MAX
from app.domain.enums import Category, SiteKey
from app.services.catalog_service import MAX_HISTORY_DAYS
from app.services.spec_filters import parse_spec_filters

router = APIRouter(tags=["catalog"])

MAX_PAGE_SIZE = 100
MAX_PAGE = 10_000  # page × page_size ≤ 1.000.000 (cận `CatalogFilters.offset`)
ProductSortParam = Literal["price_asc", "price_desc", "rating_desc", "updated_desc"]
ProductId = Annotated[int, Path(description="Id sản phẩm; id không tồn tại hoặc ngoài miền → 404")]
ShortText = Annotated[str, Field(max_length=100)]


@router.get(
    "/products",
    response_model=ProductListResponse,
    summary="Tìm sản phẩm đã thu thập",
    description=(
        "Lọc theo thông số bằng tham số `spec.<field>__<op>=<value>` (cần `category`), ví dụ "
        "`spec.gpu_rank__gte=40`, `spec.ram_gb__gte=16`, `spec.connection__contains_any="
        "wireless,bluetooth`. Trường và toán tử hợp lệ lấy từ `GET /categories`."
    ),
    responses=error_responses(422),
)
def list_products(
    request: Request,
    service: CatalogServiceDep,
    category: Category | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Từ khóa trong tên/hãng/mã")] = None,
    price_min: Annotated[int | None, Query(ge=0, le=INT8_MAX)] = None,
    price_max: Annotated[int | None, Query(ge=0, le=INT8_MAX)] = None,
    brand: Annotated[list[ShortText] | None, Query(max_length=20)] = None,
    site: Annotated[list[SiteKey] | None, Query(max_length=10)] = None,
    sort: ProductSortParam = "price_asc",
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> ProductListResponse:
    filters = CatalogFilters(
        category=category,
        q=q,
        price_min=price_min,
        price_max=price_max,
        brands=brand or [],
        sites=site or [],
        spec_filters=parse_spec_filters(dict(request.query_params), category),
        sort=sort,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    result = service.search(filters)
    return ProductListResponse(
        items=result.items,
        total=result.total,
        page=page,
        page_size=page_size,
        stale=result.stale,
        data_as_of=result.data_as_of,
    )


@router.get(
    "/products/{product_id}",
    response_model=ProductFull,
    summary="Chi tiết sản phẩm và mọi offer đang bán",
    responses=error_responses(404, 422),
)
def get_product(product_id: ProductId, service: CatalogServiceDep) -> ProductFull:
    return service.get_detail(product_id)


@router.get(
    "/products/{product_id}/price-history",
    response_model=PriceHistoryResult,
    summary="Lịch sử giá theo trang",
    responses=error_responses(404, 422),
)
def get_price_history(
    product_id: ProductId,
    service: CatalogServiceDep,
    days: Annotated[int, Query(ge=1, le=MAX_HISTORY_DAYS)] = 30,
) -> PriceHistoryResult:
    return service.price_history(product_id, days)


@router.post(
    "/compare",
    response_model=Comparison,
    summary="So sánh 2–5 sản phẩm",
    responses=error_responses(404, 422),
)
def compare_products(body: CompareRequest, service: CompareServiceDep) -> Comparison:
    return service.compare(body.product_ids)
