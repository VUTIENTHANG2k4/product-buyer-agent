"""Nhóm sản phẩm và trường lọc được (docs/07 §3.3)."""

from fastapi import APIRouter

from app.api.deps import CatalogServiceDep
from app.api.schemas import CategoriesResponse

router = APIRouter(tags=["catalog"])


@router.get(
    "/categories",
    response_model=CategoriesResponse,
    summary="Nhóm sản phẩm, tầng, số sản phẩm và trường lọc",
)
def list_categories(service: CatalogServiceDep) -> CategoriesResponse:
    return CategoriesResponse(items=service.categories())
