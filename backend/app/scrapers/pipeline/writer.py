"""Lưu kết quả thu thập: offer (gộp dữ liệu đã có), lịch sử giá và bộ đếm của lượt."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.repositories import (
    OfferRepository,
    OfferUpsert,
    PriceHistoryRepository,
    ProductRepository,
    ScrapeRunRepository,
)
from app.domain.dto import ListingItem, ProductDetail
from app.domain.enums import Category, PriceType, SiteKey, StockStatus
from app.normalize.price import MAX_PRICE_VND, MIN_PRICE_VND
from app.normalize.url import clean_url
from app.scrapers.base import SiteConfig
from app.scrapers.pipeline.resolve import (
    ProductResolver,
    UnpricedItem,
    check_item_url,
    find_existing_offer,
    url_key,
)
from app.scrapers.pipeline.state import (
    Progress,
    RunContext,
    SessionFactory,
    require_offer_id,
    require_run,
)

logger = logging.getLogger(__name__)


class OfferWriter:
    """Ghi offer và lịch sử giá: một trang danh sách mỗi transaction, từng mục một savepoint;
    làm mới giá một offer từ trang chi tiết. Mọi hàm đồng bộ (chạy qua `asyncio.to_thread`)."""

    def __init__(
        self,
        session_factory: SessionFactory,
        now: Callable[[], datetime],
        resolver: ProductResolver,
    ) -> None:
        self._session_factory = session_factory
        self._now = now
        self._resolver = resolver

    def save_page(
        self,
        config: SiteConfig,
        context: RunContext,
        progress: Progress,
        prepared: list[tuple[ListingItem, ProductDetail | None]],
        skipped: int,
    ) -> None:
        moment = self._now()
        parsed = failed = upserted = changes = unsafe = 0
        changed: list[int] = []
        seen = set(progress.seen_urls)
        with self._session_factory() as session:
            for item, detail in prepared:
                parsed += 1
                key = url_key(item)
                if key is not None and key in seen:
                    continue  # cùng URL xuất hiện lại trong lượt: bản đầu tiên thắng
                if key is not None:
                    seen.add(key)
                try:
                    with session.begin_nested():
                        offer_id, price_changed = self.save_item(
                            session, config, context.category, item, detail, moment
                        )
                except (ValueError, ValidationError, SQLAlchemyError) as exc:
                    failed += 1
                    if not isinstance(exc, UnpricedItem):
                        unsafe += 1
                    logger.warning(
                        "[run %s] không lưu được mục (%s): %s",
                        context.run_id,
                        type(exc).__name__,
                        str(item.url)[:120],
                    )
                    continue
                upserted += 1
                if price_changed:
                    changes += 1
                    changed.append(offer_id)
            parsed += skipped  # thẻ parser không đọc được vẫn là mục đã thấy
            failed += skipped
            unsafe += skipped
            totals = {
                "pages_fetched": progress.pages + 1,
                "items_parsed": progress.parsed + parsed,
                "items_failed": progress.failed + failed,
                "offers_upserted": progress.upserted + upserted,
                "price_changes": progress.price_changes + changes,
            }
            runs = ScrapeRunRepository(session)
            runs.update_counters(require_run(runs, context.run_id), **totals)
            session.commit()
        progress.pages += 1
        progress.seen_urls = seen
        progress.parsed += parsed
        progress.failed += failed
        progress.unsafe += unsafe
        progress.upserted += upserted
        progress.price_changes += changes
        progress.changed_ids.extend(changed)

    def save_item(
        self,
        session: Session,
        config: SiteConfig,
        category: Category,
        item: ListingItem,
        detail: ProductDetail | None,
        moment: datetime,
    ) -> tuple[int, bool]:
        """Lưu một mục; trả (offer_id, giá có đổi không). Ném `ValueError` nếu mục không hợp lệ."""
        if item.price is None or not MIN_PRICE_VND <= item.price <= MAX_PRICE_VND:
            raise UnpricedItem(f"price {item.price!r} is missing or out of range")
        url = clean_url(str(item.url))
        check_item_url(config, url)
        offers = OfferRepository(session)
        existing = find_existing_offer(offers, url)
        if existing is not None:
            url = (
                existing.url
            )  # giữ URL đã lưu (có thể là bản http/https còn lại của cùng sản phẩm)

        # `upsert` ghi đè cả None/{}: gộp với dữ liệu đã có để lượt không tải chi tiết không xóa nó.
        raw_specs: dict[str, Any] = {}
        if existing is not None:
            raw_specs.update(existing.raw_specs)
        raw_specs.update(item.raw_specs)
        if detail is not None:
            raw_specs.update(detail.raw_specs)
        resolution = self._resolver(session, category, item, detail, raw_specs)
        rating = item.rating if item.rating is not None else (existing.rating if existing else None)
        rating_count = (
            item.rating_count
            if item.rating_count is not None
            else (existing.rating_count if existing else None)
        )
        site_sku = item.site_sku or (existing.site_sku if existing else None)

        result = offers.upsert(
            OfferUpsert(
                product_id=resolution.product_id,
                site=item.site,
                url=url,
                title=item.title,
                price=item.price,
                list_price=item.list_price,
                price_type=item.price_type,
                # Thẻ danh sách không cho biết tồn kho (GearVN): giữ giá trị đã biết thay vì xóa nó.
                stock_status=(
                    item.stock_status
                    if item.stock_status is not StockStatus.unknown or existing is None
                    else existing.stock_status
                ),
                site_sku=site_sku,
                rating=rating,
                rating_count=rating_count,
                raw_specs=raw_specs,
                match_method=resolution.method,
                match_score=resolution.score,
            ),
            now=moment,
        )
        snapshot = PriceHistoryRepository(session).record_snapshot(result.offer, now=moment)
        return require_offer_id(result.offer), snapshot.price_changed

    def refresh_targets(
        self, site: SiteKey, category: Category, offer_ids: Sequence[int]
    ) -> list[tuple[int, str]]:
        """(id, url) của các offer còn hoạt động thuộc đúng trang và nhóm đã yêu cầu."""
        with self._session_factory() as session:
            offers = OfferRepository(session)
            products = ProductRepository(session)
            targets: list[tuple[int, str]] = []
            for offer_id in dict.fromkeys(offer_ids):
                offer = offers.get(offer_id)
                if offer is None or not offer.is_active or offer.site is not site:
                    continue
                product = products.get(offer.product_id)
                if product is not None and product.category is category:
                    targets.append((require_offer_id(offer), offer.url))
            return targets

    def save_refresh(self, offer_id: int, detail: ProductDetail) -> bool:
        """Ghi giá từ trang chi tiết vào offer; trả `True` nếu `price` đổi so với lần ghi trước
        (loại giá và tồn kho vẫn được lưu vào lịch sử nhưng không tính là đổi giá)."""
        moment = self._now()
        with self._session_factory() as session:
            offers = OfferRepository(session)
            offer = offers.get(offer_id)
            if offer is None or detail.price is None:
                raise ValueError(f"offer {offer_id} is missing or the page has no price")
            keep_price_type = detail.price_type is PriceType.unknown
            list_price = offer.list_price if keep_price_type else detail.list_price
            price_type = offer.price_type if keep_price_type else detail.price_type
            if (
                keep_price_type
                and price_type is PriceType.sale
                and list_price is not None
                and detail.price >= list_price
            ):
                list_price, price_type = None, PriceType.regular  # khuyến mãi đã kết thúc
            with session.begin_nested():
                result = offers.upsert(
                    OfferUpsert(
                        product_id=offer.product_id,
                        site=offer.site,
                        url=offer.url,
                        title=offer.title,
                        price=detail.price,
                        list_price=list_price,
                        price_type=price_type,
                        stock_status=(
                            offer.stock_status
                            if detail.stock_status is StockStatus.unknown
                            else detail.stock_status
                        ),
                        site_sku=offer.site_sku,
                        rating=offer.rating,
                        rating_count=offer.rating_count,
                        raw_specs=dict(offer.raw_specs),
                        match_method=offer.match_method,
                        match_score=offer.match_score,
                    ),
                    now=moment,
                )
                snapshot = PriceHistoryRepository(session).record_snapshot(result.offer, now=moment)
            session.commit()
            return snapshot.price_changed
