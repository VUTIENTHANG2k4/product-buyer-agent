"""Tìm kiếm và đọc danh mục sản phẩm đã thu thập (docs/05 §3, docs/07 §3.3).

Chỉ đọc CSDL, không gọi mạng. Giá so sánh là giá hiệu lực (docs/04 §4); offer hết hàng không vào
giá thấp nhất trừ khi `include_out_of_stock`. Dữ liệu cũ hơn 24 giờ được đánh dấu `stale`.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session

from app.db.models import Offer, utc_now
from app.db.repositories import (
    OfferRepository,
    PriceHistoryRepository,
    ProductQuery,
    ProductRepository,
    effective_price_of,
)
from app.domain.catalog import (
    CatalogFilters,
    CatalogSearchResult,
    PriceHistoryResult,
    PricePointView,
    ProductFull,
    ProductRow,
    ProductSummary,
    RowOffer,
    SiteSeries,
)
from app.domain.enums import StockStatus
from app.domain.errors import ProductNotFound, ValidationFailed
from app.services.views import (
    Clock,
    aware_now,
    key_specs,
    sellable,
    to_offer_view,
    to_product_full,
)

STALE_AFTER = timedelta(hours=24)
MAX_HISTORY_DAYS = 180


def _applied(filters: CatalogFilters) -> dict[str, Any]:
    """Bộ lọc thật sự áp dụng (bỏ giá trị mặc định/rỗng) để hiển thị cho người dùng và agent."""
    data = filters.model_dump(mode="json", exclude_none=True)
    applied = {name: value for name, value in data.items() if value not in ([], False, 0)}
    applied["sort"] = filters.sort
    applied["limit"] = filters.limit
    return applied


def _offer_matches(offer: Offer, filters: CatalogFilters) -> bool:
    """Cùng điều kiện offer với `ProductRepository.search`, để offer tốt nhất khớp `min_price`."""
    price = effective_price_of(offer)
    return (
        (not filters.sites or offer.site in filters.sites)
        and (filters.price_min is None or price >= filters.price_min)
        and (filters.price_max is None or price <= filters.price_max)
    )


class CatalogService:
    def __init__(self, session: Session, *, now: Clock = utc_now) -> None:
        self._session = session
        self._now = now
        self._products = ProductRepository(session)
        self._offers = OfferRepository(session)

    def search(self, filters: CatalogFilters) -> CatalogSearchResult:
        """Sản phẩm khớp bộ lọc, mỗi sản phẩm kèm offer rẻ nhất khớp điều kiện trang/giá."""
        now = aware_now(self._now)
        query = ProductQuery(
            category=filters.category,
            brands=filters.brands,
            sites=filters.sites,
            price_min=filters.price_min,
            price_max=filters.price_max,
            spec_filters=filters.spec_filters,
            text=filters.q,
            include_out_of_stock=filters.include_out_of_stock,
            # Chưa có điểm liên quan: `relevance` xếp theo giá thấp nhất (docs/04 §3).
            sort="price_asc" if filters.sort == "relevance" else filters.sort,
            limit=filters.limit,
            offset=filters.offset,
        )
        page = self._products.search(query)
        ids = [hit.product.id for hit in page.items if hit.product.id is not None]
        offers_by_product = self._offers.list_for_products(ids)

        items: list[ProductSummary] = []
        for hit in page.items:
            product = hit.product
            if product.id is None:  # pragma: no cover - đọc từ CSDL luôn có id
                continue
            offers = [
                offer
                for offer in sellable(
                    offers_by_product[product.id],
                    include_out_of_stock=filters.include_out_of_stock,
                )
                if _offer_matches(offer, filters)
            ]
            if not offers:  # pragma: no cover - truy vấn đã bảo đảm có offer khớp
                continue
            best = offers[0]
            prices = [effective_price_of(offer) for offer in offers]
            items.append(
                ProductSummary(
                    product_id=product.id,
                    name=product.canonical_name,
                    brand=product.brand,
                    category=product.category,
                    key_specs=key_specs(product.category, product.specs),
                    min_price=min(prices),
                    max_price=max(prices),
                    best_offer=to_offer_view(best),
                    offers_count=len(offers),
                    in_stock=best.stock_status != StockStatus.out_of_stock,
                    image_url=product.image_url,
                )
            )

        data_as_of = min((item.best_offer.scraped_at for item in items), default=None)
        return CatalogSearchResult(
            total=page.total,
            items=items,
            stale=data_as_of is not None and now - data_as_of > STALE_AFTER,
            data_as_of=data_as_of,
            applied_filters=_applied(filters),
        )

    def get_detail(self, product_id: int) -> ProductFull:
        """Thông số và mọi offer đang bán của một sản phẩm (`ProductNotFound` nếu không có)."""
        found = self.get_many([product_id])
        if not found:
            raise ProductNotFound(details={"product_id": product_id})
        return found[0]

    def get_many(self, product_ids: list[int]) -> list[ProductFull]:
        """Nhiều sản phẩm theo thứ tự `product_ids`; id không tồn tại bị bỏ qua."""
        products = self._products.get_many(product_ids)
        ids = [product.id for product in products if product.id is not None]
        offers_by_product = self._offers.list_for_products(ids)
        return [
            to_product_full(product, offers_by_product[product.id])
            for product in products
            if product.id is not None
        ]

    def rows(self, product_ids: list[int], *, max_offers: int = 5) -> list[ProductRow]:
        """Dòng bảng kết quả theo thứ tự `product_ids` (id lạ bị bỏ), mỗi dòng tối đa `max_offers`
        offer còn mua được, rẻ nhất trước. Giá luôn lấy từ CSDL."""
        products = self._products.get_many(product_ids)
        ids = [product.id for product in products if product.id is not None]
        offers_by_product = self._offers.list_for_products(ids)
        rows: list[ProductRow] = []
        for product in products:
            if product.id is None:  # pragma: no cover - đọc từ CSDL luôn có id
                continue
            offers = sellable(offers_by_product[product.id])[:max_offers]
            views = [to_offer_view(offer) for offer in offers]
            rows.append(
                ProductRow(
                    product_id=product.id,
                    name=product.canonical_name,
                    brand=product.brand,
                    category=product.category,
                    key_specs=key_specs(product.category, product.specs),
                    min_price=views[0].effective_price if views else None,
                    offers=[
                        RowOffer(
                            site=view.site,
                            price=view.effective_price,
                            price_type=view.price_type,
                            stock_status=view.stock_status,
                            url=view.url,
                            scraped_at=view.scraped_at,
                        )
                        for view in views
                    ],
                    image_url=product.image_url,
                )
            )
        return rows

    def price_history(self, product_id: int, days: int = 30) -> PriceHistoryResult:
        """Chuỗi giá theo trang trong `days` ngày gần nhất (1..180), gồm cả offer đã tắt."""
        if not 1 <= days <= MAX_HISTORY_DAYS:
            raise ValidationFailed(
                f"days phải trong khoảng 1..{MAX_HISTORY_DAYS}", details={"days": days}
            )
        if self._products.get(product_id) is None:
            raise ProductNotFound(details={"product_id": product_id})
        since: datetime = aware_now(self._now) - timedelta(days=days)
        points = PriceHistoryRepository(self._session).series_for_product(product_id, since=since)
        by_site: dict[str, SiteSeries] = {}
        for point in points:
            series = by_site.setdefault(point.site.value, SiteSeries(site=point.site, points=[]))
            series.points.append(
                PricePointView(t=point.scraped_at, price=point.price, price_type=point.price_type)
            )
        prices = [point.price for point in points]
        return PriceHistoryResult(
            series=list(by_site.values()),
            min_price=min(prices) if prices else None,
            max_price=max(prices) if prices else None,
        )
