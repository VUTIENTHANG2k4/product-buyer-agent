"""Lưu kết quả thu thập: offer (gộp dữ liệu đã có), lịch sử giá và bộ đếm của lượt."""

import logging
from collections.abc import Callable, Collection, Sequence
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
from app.normalize.extract import SpecsExtraction, extract_specs
from app.normalize.llm_extract import LlmSpecsFiller
from app.normalize.price import MAX_PRICE_VND, MIN_PRICE_VND
from app.normalize.url import clean_url
from app.scrapers.base import SiteConfig
from app.scrapers.pipeline.resolve import (
    FactorySpecsCache,
    ProductResolver,
    UnpricedItem,
    check_item_url,
    find_existing_offer,
    merge_raw_specs,
    url_key,
)
from app.scrapers.pipeline.state import (
    PreparedItem,
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
        spec_filler: LlmSpecsFiller | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._now = now
        self._resolver = resolver
        self._spec_filler = spec_filler

    def prefill_specs(
        self,
        config: SiteConfig,
        category: Category,
        prepared: list[PreparedItem],
        seen: Collection[str] = (),
    ) -> list[PreparedItem]:
        """Trích thông số (luật rồi LLM dự phòng) cho cả trang TRƯỚC khi mở giao dịch lưu (T6.7a).

        LLM gọi đồng bộ nên không được chờ nó khi đang giữ transaction của trang. Cache LLM ghi
        bằng session riêng và commit ngay. Không bao giờ ném lỗi: mục không làm sẵn được thì giữ
        `extraction=None` và bước lưu tự trích theo luật. Mục `save_item` chắc chắn từ chối (không
        giá, URL ngoài trang, trùng URL đã gặp trong lượt) không tốn lần gọi LLM nào.
        """
        filler = self._spec_filler
        if filler is None:
            return prepared
        raws: list[dict[str, Any] | None] = []
        try:
            with self._session_factory() as session:  # phiên ngắn: chỉ đọc offer đã lưu
                offers = OfferRepository(session)
                page_seen = set(seen)
                for entry in prepared:
                    price = entry.item.price
                    key = url_key(entry.item)
                    if (
                        price is None
                        or key is None
                        or not MIN_PRICE_VND <= price <= MAX_PRICE_VND
                        or key in page_seen
                    ):
                        raws.append(None)  # bước lưu sẽ bỏ mục này: khỏi gọi LLM
                        continue
                    page_seen.add(key)
                    try:
                        url = clean_url(str(entry.item.url))
                        check_item_url(config, url)
                        found = find_existing_offer(offers, url)
                    except ValueError:  # gồm InvalidItemUrl: mục sẽ lỗi ở bước lưu
                        raws.append(None)
                        continue
                    raws.append(
                        merge_raw_specs(
                            found.raw_specs if found else None, entry.item, entry.detail
                        )
                    )
        except SQLAlchemyError:
            logger.warning("Không đọc được offer cũ để làm sẵn thông số", exc_info=True)
            return prepared
        cache = FactorySpecsCache(self._session_factory)
        result: list[PreparedItem] = []
        for entry, raw in zip(prepared, raws, strict=True):
            extraction: SpecsExtraction | None = None
            if raw is not None:
                try:
                    extraction = extract_specs(category, entry.item.title, raw)
                    if extraction.missing:
                        extraction = filler(cache, category, entry.item.title, raw, extraction)
                except Exception:
                    logger.warning("Làm sẵn thông số lỗi, dùng luật khi lưu", exc_info=True)
                    extraction = None
            result.append(PreparedItem(entry.item, entry.detail, extraction))
        return result

    def save_page(
        self,
        config: SiteConfig,
        context: RunContext,
        progress: Progress,
        prepared: list[PreparedItem],
        skipped: int,
    ) -> None:
        """Lưu một trang danh sách trong một transaction (mỗi mục một savepoint, URL trùng trong
        lượt bỏ qua), cập nhật bộ đếm của lượt rồi cộng vào `progress`."""
        moment = self._now()
        parsed = failed = upserted = changes = unsafe = 0
        changed: list[int] = []
        seen = set(progress.seen_urls)
        with self._session_factory() as session:
            for entry in prepared:
                item = entry.item
                parsed += 1
                key = url_key(item)
                if key is not None and key in seen:
                    continue  # cùng URL xuất hiện lại trong lượt: bản đầu tiên thắng
                if key is not None:
                    seen.add(key)
                try:
                    with session.begin_nested():
                        offer_id, price_changed = self.save_item(
                            session,
                            config,
                            context.category,
                            item,
                            entry.detail,
                            moment,
                            extraction=entry.extraction,
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
        *,
        extraction: SpecsExtraction | None = None,
    ) -> tuple[int, bool]:
        """Lưu một mục; trả (offer_id, giá có đổi không). Ném `ValueError` nếu mục không hợp lệ."""
        if item.price is None or not MIN_PRICE_VND <= item.price <= MAX_PRICE_VND:
            raise UnpricedItem(f"price {item.price!r} is missing or out of range")
        url = clean_url(str(item.url))
        check_item_url(config, url)
        offers = OfferRepository(session)
        existing = find_existing_offer(offers, url)
        if existing is not None:
            # giữ URL đã lưu (có thể là bản http/https còn lại của cùng sản phẩm)
            url = existing.url

        # `upsert` ghi đè cả None/{}: gộp với dữ liệu đã có để lượt không tải chi tiết không xóa nó.
        raw_specs = merge_raw_specs(existing.raw_specs if existing else None, item, detail)
        resolution = self._resolver(
            session, category, item, detail, raw_specs, extraction=extraction
        )
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
