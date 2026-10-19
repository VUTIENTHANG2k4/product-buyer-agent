"""Repository cho `Product`: tìm theo khóa model, cập nhật specs, tìm kiếm theo specs JSONB và giá.

Lọc specs dùng toán tử JSONB của SQLAlchemy (không SQL thô); tên trường luôn là tham số ràng buộc.
"""

from collections.abc import Mapping
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, and_, case, false, func, or_
from sqlalchemy import select as core_select
from sqlmodel import Session, col, select

from app.db.models import Offer, Product
from app.db.repositories.offers import effective_price
from app.domain.dto import INT8_MAX, SpecFilter, Vnd
from app.domain.enums import Category, SiteKey

ProductSort = Literal["price_asc", "price_desc", "rating_desc"]


class ProductQuery(BaseModel):
    """Điều kiện tìm sản phẩm. `relevance` và từ khóa do `catalog_service` ánh xạ trước khi gọi."""

    model_config = ConfigDict(extra="forbid")

    category: Category | None = None
    brands: list[str] = Field(default_factory=list)
    sites: list[SiteKey] = Field(default_factory=list)  # rỗng = mọi trang
    price_min: Vnd | None = None  # theo giá hiệu lực của offer đang bán (VND)
    price_max: Vnd | None = None
    spec_filters: list[SpecFilter] = Field(default_factory=list)
    sort: ProductSort = "price_asc"
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    offset: int = Field(default=0, ge=0, le=INT8_MAX, strict=True)


class ProductHit(NamedTuple):
    """Một sản phẩm khớp, kèm số liệu giá tổng hợp trên các offer khớp điều kiện (VND)."""

    product: Product
    min_price: int
    max_price: int
    offers_count: int
    best_rating: float | None


class ProductPage(NamedTuple):
    total: int  # số sản phẩm khớp, không tính limit/offset
    items: list[ProductHit]


def spec_condition(spec_filter: SpecFilter) -> ColumnElement[bool]:
    """Điều kiện SQL cho một `SpecFilter` trên cột `product.specs` (JSONB).

    Số (kể cả số thực) so sánh qua `CAST … AS FLOAT` và chỉ khi giá trị JSON thật sự là số, nên
    trường thiếu hoặc khác kiểu thì không khớp và không làm lỗi truy vấn.
    """
    specs = col(Product.specs)
    field, op, value = spec_filter.field, spec_filter.op, spec_filter.value
    node = specs[field]

    if op == "contains":
        return specs.contains({field: [value]})
    if op == "contains_any":
        values = value if isinstance(value, list) else [value]
        # `false()` đầu tiên: danh sách rỗng thì không khớp gì (or_() rỗng sẽ khớp tất cả).
        any_of: ColumnElement[bool] = or_(
            false(), *(specs.contains({field: [item]}) for item in values)
        )
        return any_of
    if op == "in":
        values = value if isinstance(value, list) else [value]
        member: ColumnElement[bool] = node.as_string().in_([str(item) for item in values])
        return member

    if isinstance(value, bool):
        typed = case((func.jsonb_typeof(node) == "boolean", node.as_boolean()), else_=None)
        return typed == value
    if isinstance(value, int | float):
        typed = case((func.jsonb_typeof(node) == "number", node.as_float()), else_=None)
        if op == "gte":
            return typed >= value
        if op == "lte":
            return typed <= value
        return typed == value
    # Chuỗi: DTO chỉ cho `eq` với giá trị đơn kiểu str.
    equal: ColumnElement[bool] = node.as_string() == str(value)
    return equal


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, product: Product) -> Product:
        self._session.add(product)
        self._session.flush()
        return product

    def get(self, product_id: int) -> Product | None:
        return self._session.get(Product, product_id)

    def get_many(self, product_ids: list[int]) -> list[Product]:
        """Các sản phẩm tồn tại trong `product_ids`, theo thứ tự của danh sách (id lạ bị bỏ)."""
        if not product_ids:
            return []
        rows = self._session.exec(select(Product).where(col(Product.id).in_(product_ids))).all()
        by_id = {product.id: product for product in rows}
        return [by_id[pid] for pid in product_ids if pid in by_id]

    def find_by_model_key(self, category: Category, brand: str, model_code: str) -> Product | None:
        """Sản phẩm trùng (category, brand, model_code), khớp với chỉ mục unique một phần."""
        statement = select(Product).where(
            Product.category == category,
            Product.brand == brand,
            Product.model_code == model_code,
        )
        return self._session.exec(statement).first()

    def update_specs(
        self, product: Product, specs: Mapping[str, Any], specs_confidence: float | None = None
    ) -> Product:
        """Thay toàn bộ `specs` (gán lại dict vì JSONB không theo dõi sửa tại chỗ)."""
        product.specs = dict(specs)
        if specs_confidence is not None:
            product.specs_confidence = specs_confidence
        self._session.flush()
        return product

    def search(self, query: ProductQuery) -> ProductPage:
        """Sản phẩm có ít nhất một offer đang bán khớp điều kiện giá/trang và specs khớp bộ lọc."""
        price = effective_price()
        offer_conditions: list[ColumnElement[bool]] = [col(Offer.is_active).is_(True)]
        if query.sites:
            offer_conditions.append(col(Offer.site).in_(query.sites))
        if query.price_min is not None:
            offer_conditions.append(price >= query.price_min)
        if query.price_max is not None:
            offer_conditions.append(price <= query.price_max)
        offers = (
            core_select(
                col(Offer.product_id).label("product_id"),
                func.min(price).label("min_price"),
                func.max(price).label("max_price"),
                func.count().label("offers_count"),
                func.max(Offer.rating).label("best_rating"),
            )
            .where(and_(*offer_conditions))
            .group_by(col(Offer.product_id))
            .subquery()
        )

        base = core_select(
            Product,
            offers.c.min_price,
            offers.c.max_price,
            offers.c.offers_count,
            offers.c.best_rating,
        ).join(offers, offers.c.product_id == Product.id)
        if query.category is not None:
            base = base.where(col(Product.category) == query.category)
        if query.brands:
            lowered = [brand.lower() for brand in query.brands]
            base = base.where(func.lower(Product.brand).in_(lowered))
        for spec_filter in query.spec_filters:
            base = base.where(spec_condition(spec_filter))

        total = self._session.exec(select(func.count()).select_from(base.subquery())).one()

        if query.sort == "price_desc":
            order = [offers.c.min_price.desc()]
        elif query.sort == "rating_desc":
            order = [offers.c.best_rating.desc().nulls_last(), offers.c.min_price.asc()]
        else:
            order = [offers.c.min_price.asc()]
        page = base.order_by(*order, col(Product.id)).limit(query.limit).offset(query.offset)
        items = [
            ProductHit(product, int(low), int(high), int(count), rating)
            for product, low, high, count, rating in self._session.execute(page)
        ]
        return ProductPage(total=int(total), items=items)
