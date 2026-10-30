"""Repository cho `Product`: tìm theo khóa model, cập nhật specs, tìm kiếm theo specs JSONB và giá.

Lọc specs dùng toán tử JSONB của SQLAlchemy (không SQL thô); tên trường luôn là tham số ràng buộc.
"""

from collections.abc import Mapping
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, and_, case, false, func, or_
from sqlalchemy import select as core_select
from sqlmodel import Session, col, select

from app.db.models import Offer, PriceAlert, Product, ShoppingListItem
from app.db.repositories.ids import fits_int4, keep_valid
from app.db.repositories.offers import effective_price
from app.domain.dto import INT8_MAX, SpecFilter, Vnd
from app.domain.enums import Category, SiteKey, StockStatus

ProductSort = Literal["price_asc", "price_desc", "rating_desc", "updated_desc"]


class ProductQuery(BaseModel):
    """Điều kiện tìm sản phẩm. `relevance` và từ khóa do `catalog_service` ánh xạ trước khi gọi."""

    model_config = ConfigDict(extra="forbid")

    category: Category | None = None
    brands: list[str] = Field(default_factory=list)
    sites: list[SiteKey] = Field(default_factory=list)  # rỗng = mọi trang
    price_min: Vnd | None = None  # theo giá hiệu lực của offer đang bán (VND)
    price_max: Vnd | None = None
    spec_filters: list[SpecFilter] = Field(default_factory=list)
    # Mọi từ (tách theo khoảng trắng) phải xuất hiện trong tên chuẩn, hãng hoặc mã model.
    text: str | None = Field(default=None, max_length=200)
    # Mặc định bỏ offer hết hàng khỏi giá/số offer; sản phẩm chỉ còn offer hết hàng thì không hiện.
    include_out_of_stock: bool = False
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
        return self._session.get(Product, product_id) if fits_int4(product_id) else None

    def get_many(self, product_ids: list[int]) -> list[Product]:
        """Các sản phẩm tồn tại trong `product_ids`, theo thứ tự của danh sách (id lạ bị bỏ)."""
        valid = keep_valid(product_ids)
        if not valid:
            return []
        rows = self._session.exec(select(Product).where(col(Product.id).in_(valid))).all()
        by_id = {product.id: product for product in rows}
        return [by_id[pid] for pid in product_ids if pid in by_id]

    def count_by_category(self) -> dict[Category, int]:
        """Số sản phẩm còn ít nhất một offer đang bán, theo nhóm (nhóm không có sản phẩm: vắng)."""
        has_offer = (
            select(Offer.id)
            .where(col(Offer.product_id) == col(Product.id), col(Offer.is_active).is_(True))
            .exists()
        )
        statement = (
            select(Product.category, func.count()).where(has_offer).group_by(col(Product.category))
        )
        return {Category(category): int(count) for category, count in self._session.exec(statement)}

    def find_by_model_key(self, category: Category, brand: str, model_code: str) -> Product | None:
        """Sản phẩm trùng (category, brand, model_code), khớp với chỉ mục unique một phần."""
        statement = select(Product).where(
            Product.category == category,
            Product.brand == brand,
            Product.model_code == model_code,
        )
        return self._session.exec(statement).first()

    def list_by_brand(self, category: Category, brand: str) -> list[Product]:
        """Mọi sản phẩm cùng nhóm và hãng (ứng viên để ghép offer mới), theo id tăng dần."""
        statement = (
            select(Product)
            .where(Product.category == category, Product.brand == brand)
            .order_by(col(Product.id))
        )
        return list(self._session.exec(statement))

    def set_model_code(self, product: Product, model_code: str) -> Product:
        """Gán mã model cho sản phẩm chưa có mã. Người gọi kiểm tra mã chưa thuộc sản phẩm khác
        (chỉ mục unique `(category, brand, model_code)`), nếu không `flush` sẽ ném lỗi ràng buộc."""
        product.model_code = model_code
        self._session.flush()
        return product

    def set_image_url(self, product: Product, image_url: str) -> Product:
        """Gán ảnh đại diện (người gọi quyết định có ghi đè ảnh cũ hay không)."""
        product.image_url = image_url
        self._session.flush()
        return product

    def update_specs(
        self, product: Product, specs: Mapping[str, Any], specs_confidence: float | None = None
    ) -> Product:
        """Thay toàn bộ `specs` (gán lại dict vì JSONB không theo dõi sửa tại chỗ)."""
        product.specs = dict(specs)
        if specs_confidence is not None:
            product.specs_confidence = specs_confidence
        self._session.flush()
        return product

    def set_identity(
        self, product: Product, *, brand: str, canonical_name: str, model_code: str | None
    ) -> Product:
        """Đặt lại hãng, tên chuẩn và mã model (script ghép lại, T5.4). Mã phải chưa thuộc sản
        phẩm khác cùng (category, brand), nếu không `flush` ném lỗi ràng buộc unique."""
        product.brand = brand
        product.canonical_name = canonical_name
        product.model_code = model_code
        self._session.flush()
        return product

    def is_referenced(self, product_id: int, *, count_offers: bool = True) -> bool:
        """Sản phẩm còn offer (bỏ qua khi `count_offers=False`), nằm trong danh sách mua hoặc có
        cảnh báo giá (mọi trạng thái)."""
        models = (
            (Offer, ShoppingListItem, PriceAlert)
            if count_offers
            else (ShoppingListItem, PriceAlert)
        )
        for model in models:
            statement = select(model.id).where(model.product_id == product_id).limit(1)
            if self._session.exec(statement).first() is not None:
                return True
        return False

    def delete(self, product: Product) -> None:
        """Xóa sản phẩm; người gọi kiểm `is_referenced` trước (offer chặn xóa bằng khóa ngoại,
        cảnh báo giá thì bị xóa theo)."""
        self._session.delete(product)
        self._session.flush()

    def search(self, query: ProductQuery) -> ProductPage:
        """Sản phẩm có ít nhất một offer đang bán khớp điều kiện giá/trang và specs khớp bộ lọc."""
        price = effective_price()
        offer_conditions: list[ColumnElement[bool]] = [col(Offer.is_active).is_(True)]
        if not query.include_out_of_stock:
            offer_conditions.append(col(Offer.stock_status) != StockStatus.out_of_stock)
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
                func.max(Offer.scraped_at).label("latest_scraped_at"),
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
        for term in (query.text or "").split():
            pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            base = base.where(
                or_(
                    col(Product.canonical_name).ilike(pattern, escape="\\"),
                    col(Product.brand).ilike(pattern, escape="\\"),
                    col(Product.model_code).ilike(pattern, escape="\\"),
                )
            )
        for spec_filter in query.spec_filters:
            base = base.where(spec_condition(spec_filter))

        total = self._session.exec(select(func.count()).select_from(base.subquery())).one()

        if query.sort == "price_desc":
            order = [offers.c.min_price.desc()]
        elif query.sort == "rating_desc":
            order = [offers.c.best_rating.desc().nulls_last(), offers.c.min_price.asc()]
        elif query.sort == "updated_desc":
            order = [offers.c.latest_scraped_at.desc(), offers.c.min_price.asc()]
        else:
            order = [offers.c.min_price.asc()]
        page = base.order_by(*order, col(Product.id)).limit(query.limit).offset(query.offset)
        items = [
            ProductHit(product, int(low), int(high), int(count), rating)
            for product, low, high, count, rating in self._session.execute(page)
        ]
        return ProductPage(total=int(total), items=items)
