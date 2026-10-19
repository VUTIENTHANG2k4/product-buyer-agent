"""Pipeline thu thập: scraper → chuẩn hóa → repository (docs/06 §7, docs/03 §5.2).

Đây là file duy nhất trong `app/scrapers` được import `app.db`. Pipeline sở hữu transaction: mỗi
trang danh sách được lưu trong một transaction, từng mục trong một savepoint để lỗi lưu một mục chỉ
tính vào `items_failed`. Repository đồng bộ nên mọi thao tác CSDL chạy qua `asyncio.to_thread`.
Pipeline KHÔNG gọi `app.services`; đánh giá cảnh báo giá do `scrape_service` làm với kết quả trả về.

Khác biệt tạm thời so với thiết kế cuối (M5 thay thế): chưa trích thông số bằng luật/LLM và chưa có
matcher, nên `resolve_product_interim` tạo một `Product` cho mỗi offer mới (offer đã có thì dùng lại
sản phẩm của nó, nhờ đó chạy lại không nhân đôi).
"""

import asyncio
import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.models import Offer, Product, ScrapeRun, utc_now
from app.db.repositories import (
    OfferRepository,
    OfferUpsert,
    PriceHistoryRepository,
    ProductRepository,
    ScrapeRunRepository,
)
from app.domain.dto import Challenge, ListingItem, ProductDetail
from app.domain.enums import Category, ChallengeKind, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import (
    ChallengeFailed,
    ChallengeNotPending,
    InvalidScrapeRequest,
    RunNotFound,
    ScrapeAlreadyRunning,
    SiteCooldown,
)
from app.normalize.brand import UNKNOWN_BRAND, detect_brand
from app.normalize.price import MAX_PRICE_VND, MIN_PRICE_VND
from app.normalize.url import clean_url, host_key
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.errors import FetchError, FetchFailed
from app.scrapers.http.types import FormFetcher
from app.scrapers.registry import get_scraper

logger = logging.getLogger(__name__)

BLOCK_COOLDOWN = timedelta(hours=24)  # nghỉ sau khi trang thật chặn (docs/02 §3)
RUNNING_STALE_AFTER = timedelta(
    hours=2
)  # RUNNING quá lâu = tiến trình đã chết, không chặn lượt mới
NEEDS_HUMAN_STALE_AFTER = timedelta(hours=1)  # bỏ cuộc nếu không ai nhập đáp án
FAILED_RATIO_LIMIT = 0.2  # items_failed / items_parsed > 20% → PARTIAL
DROP_RATIO_LIMIT = 0.5  # số sản phẩm giảm > 50% so với lượt trước → cảnh báo
DEFAULT_MAX_DETAIL_REQUESTS = 20  # giới hạn số trang chi tiết tải thêm mỗi lượt
_ACTIVE = (ScrapeStatus.PENDING, ScrapeStatus.RUNNING, ScrapeStatus.NEEDS_HUMAN)

SessionFactory = Callable[[], Session]
ProductResolver = Callable[[Session, Category, ListingItem, ProductDetail | None], int]


@dataclass(frozen=True)
class PipelineResult:
    """Kết quả một lượt (hoặc một đoạn của lượt sau `resume`).

    `changed_offer_ids` chỉ gồm offer đổi giá trong đoạn vừa chạy; `scrape_service` đánh giá cảnh
    báo sau mỗi lần gọi nên không mất offer nào khi lượt bị gián đoạn rồi tiếp tục.
    """

    run_id: int
    site: SiteKey
    category: Category
    status: ScrapeStatus
    pages_fetched: int
    items_parsed: int
    items_failed: int
    offers_upserted: int
    price_changes: int
    changed_offer_ids: tuple[int, ...]
    challenge: Challenge | None = None
    error_message: str | None = None


@dataclass
class _Progress:
    """Số liệu cộng dồn của lượt đang chạy (bắt đầu từ bộ đếm đã lưu khi `resume`)."""

    pages: int = 0
    parsed: int = 0
    failed: int = 0
    upserted: int = 0
    price_changes: int = 0
    changed_ids: list[int] = field(default_factory=list)
    seen_urls: set[str] = field(default_factory=set)  # URL đã gặp trong lượt (khử trùng)
    unsafe: int = 0  # lỗi không phải 'hết giá': thẻ hỏng, lỗi lưu → cấm tắt offer không thấy
    has_next: bool = False  # trang cuối đã tải còn trang sau (bị cắt bởi max_pages)
    detail_requests: int = 0


@dataclass(frozen=True)
class _Verdict:
    status: ScrapeStatus
    message: str | None
    deactivate: bool = False


@dataclass(frozen=True)
class _RunContext:
    run_id: int
    site: SiteKey
    category: Category
    started_at: datetime
    expect_items: bool
    previous_items: int | None  # items_parsed của lượt SUCCEEDED gần nhất


class UnpricedItem(ValueError):
    """Mục không có giá dùng được (che, ngoài miền, 0): offer cũ của nó coi như hết bán."""


class InvalidItemUrl(ValueError):
    """Liên kết của mục trỏ ra ngoài trang hoặc về chính trang danh sách: không lưu thành offer."""


# ---- gắn offer vào product (tạm thời, M5 thay bằng matcher) ----
def resolve_product_interim(
    session: Session, category: Category, item: ListingItem, detail: ProductDetail | None
) -> int:
    """`product_id` cho `item`: dùng lại sản phẩm của offer đã có, nếu không thì tạo mới.

    Sản phẩm mới có `model_code=None`, `specs={}` và `specs_confidence=0` (chưa trích thông số).
    """
    existing = OfferRepository(session).get_by_url(clean_url(str(item.url)))
    if existing is not None:
        return existing.product_id
    brand = detect_brand(item.title)
    if brand == UNKNOWN_BRAND and detail is not None and detail.brand_hint:
        brand = detect_brand(detail.brand_hint)
    product = ProductRepository(session).add(
        Product(
            category=category,
            brand=brand,
            model_code=None,
            canonical_name=item.title.strip(),
            specs={},
            specs_confidence=0.0,
            image_url=str(item.image_url) if item.image_url else None,
        )
    )
    if product.id is None:  # pragma: no cover - flush luôn gán id
        raise RuntimeError("product has no id after flush")
    return product.id


def _url_key(item: ListingItem) -> str | None:
    """URL đã làm sạch của mục, hoặc `None` nếu không làm sạch được (mục sẽ lỗi ở bước lưu)."""
    try:
        return clean_url(str(item.url))
    except ValueError:
        return None


def _check_item_url(config: SiteConfig, url: str) -> None:
    """URL mục phải cùng máy chủ với trang và không phải trang danh sách/trang chủ."""
    if host_key(url) != host_key(config.base_url):
        raise InvalidItemUrl(f"item URL is outside {config.base_url}")
    listing_paths = {urlsplit(page).path or "/" for page in config.categories.values()} | {"/"}
    if (urlsplit(url).path or "/") in listing_paths:
        raise InvalidItemUrl("item URL points to a listing page, not a product")


def _lock_key(site: SiteKey, category: Category) -> int:
    digest = hashlib.sha256(f"scrape:{site}:{category}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _error_text(exc: BaseException) -> str:
    """Thông điệp cho `ScrapeRun.error_message`: lỗi tải có URL công khai, lỗi khác chỉ lấy tên."""
    if isinstance(exc, FetchError):
        return f"{type(exc).__name__}: {exc}"[:500]
    return f"Lỗi không lường trước: {type(exc).__name__}"


class ScrapePipeline:
    def __init__(
        self,
        session_factory: SessionFactory,
        fetcher: FormFetcher,
        *,
        default_max_pages: int = 3,
        max_detail_requests: int = DEFAULT_MAX_DETAIL_REQUESTS,
        resolver: ProductResolver = resolve_product_interim,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._fetcher = fetcher
        self._default_max_pages = default_max_pages
        self._max_detail_requests = max_detail_requests
        self._resolver = resolver
        self._now = now

    # ---- API ----
    async def run(
        self,
        site: SiteKey,
        category: Category,
        trigger: ScrapeTrigger,
        *,
        max_pages: int | None = None,
    ) -> PipelineResult:
        """Một lượt thu thập (site, category).

        Ném `SiteNotAvailable` (trang chưa đăng ký/đã tắt), `SiteCooldown` (trang thật vừa chặn)
        hoặc `ScrapeAlreadyRunning`. Mọi kết cục khác (lỗi tải, challenge, lỗi không lường
        trước) được ghi vào `ScrapeRun` và trả về trong kết quả thay vì ném ra.
        """
        scraper = get_scraper(site, self._fetcher)
        if category not in scraper.config.categories:
            raise InvalidScrapeRequest(f"{site} has no category {category}")
        limit = self._limit(max_pages)
        context = await asyncio.to_thread(
            self._start_run, site, category, trigger, scraper.config.is_mock
        )
        logger.info(
            "[run %s] bắt đầu %s/%s (tối đa %s trang)", context.run_id, site, category, limit
        )
        return await self._crawl(scraper, context, _Progress(), start_page=1, max_pages=limit)

    async def resume(
        self, run_id: int, answer: str, *, max_pages: int | None = None
    ) -> PipelineResult:
        """Gửi đáp án captcha của mock-shop rồi tiếp tục lượt `NEEDS_HUMAN` từ trang đang dừng.

        Ném `RunNotFound`, `ChallengeNotPending` (lượt không chờ đáp án) hoặc `ChallengeFailed` (đáp
        án sai: lượt vẫn `NEEDS_HUMAN`, thử lại được). Phải dùng cùng `Fetcher` với lượt đầu nếu
        muốn giữ cookie phiên; một tiến trình mới vẫn được vì cookie lấy lại từ chính lần gửi này.
        """
        limit = self._limit(max_pages)
        context, progress, challenge = await asyncio.to_thread(self._claim_paused, run_id, limit)
        scraper = get_scraper(context.site, self._fetcher)
        try:
            url, data = scraper.challenge_submission(challenge, answer)
            response = await self._fetcher.post_form(url, data)
            if response.status >= 400 and response.status != 400:
                raise FetchFailed(f"challenge endpoint returned HTTP {response.status}", url=url)
        except BaseException:
            # Lượt đã chuyển sang RUNNING để chặn resume đồng thời: trả lại để thử đáp án khác.
            await asyncio.shield(asyncio.to_thread(self._release_paused, run_id, challenge))
            raise
        if response.status == 400:
            await asyncio.to_thread(self._release_paused, run_id, challenge)
            raise ChallengeFailed()
        logger.info("[run %s] đáp án đúng, tiếp tục từ trang %s", run_id, progress.pages + 1)
        return await self._crawl(
            scraper, context, progress, start_page=progress.pages + 1, max_pages=limit
        )

    def _limit(self, max_pages: int | None) -> int:
        limit = max_pages if max_pages is not None else self._default_max_pages
        if limit < 1:
            raise InvalidScrapeRequest(f"max_pages must be >= 1, got {limit}")
        return limit

    # ---- vòng đời ScrapeRun (chạy trong thread) ----
    def _start_run(
        self, site: SiteKey, category: Category, trigger: ScrapeTrigger, is_mock: bool
    ) -> _RunContext:
        moment = self._now()
        with self._session_factory() as session:
            # Khóa theo (site, category): hai lượt đồng thời không cùng vượt qua kiểm tra bên dưới.
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(site, category)}
            )
            runs = ScrapeRunRepository(session)
            active = runs.latest(site, category)
            if active is not None and self._is_active(active, moment):
                raise ScrapeAlreadyRunning(
                    details={"run_id": active.id, "status": active.status.value}
                )
            if not is_mock:
                blocked = runs.latest_blocked_since(site, moment - BLOCK_COOLDOWN)
                if blocked is not None:
                    # Nghỉ 24 giờ kể từ lúc lượt bị chặn bắt đầu; đúng mốc thì đã được chạy lại.
                    until = blocked.started_at + BLOCK_COOLDOWN
                    if until > moment:
                        raise SiteCooldown(details={"retry_after": until, "run_id": blocked.id})
            previous = runs.latest_succeeded(site, category)
            run = runs.create(site, category, trigger, now=moment)
            session.commit()
            return _RunContext(
                run_id=_require_id(run),
                site=site,
                category=category,
                started_at=moment,
                expect_items=previous is not None and previous.items_parsed > 0,
                previous_items=previous.items_parsed if previous is not None else None,
            )

    @staticmethod
    def _is_active(run: ScrapeRun, moment: datetime) -> bool:
        if run.status not in _ACTIVE:
            return False
        stale_after = (
            NEEDS_HUMAN_STALE_AFTER
            if run.status is ScrapeStatus.NEEDS_HUMAN
            else RUNNING_STALE_AFTER
        )
        return moment - run.started_at < stale_after

    def _claim_paused(self, run_id: int, limit: int) -> tuple[_RunContext, _Progress, Challenge]:
        """Chiếm lượt `NEEDS_HUMAN` (chuyển sang RUNNING) dưới khóa (site, category).

        Hai `resume` đồng thời không cùng chiếm được; lượt quá hạn (đã cho phép lượt mới chạy) và
        `max_pages` nhỏ hơn trang cần tiếp tục bị từ chối trước khi đổi bất cứ thứ gì.
        """
        moment = self._now()
        with self._session_factory() as session:
            runs = ScrapeRunRepository(session)
            peek = runs.get(run_id)
            if peek is None:
                raise RunNotFound(details={"run_id": run_id})
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": _lock_key(peek.site, peek.category)},
            )
            session.refresh(peek)  # đọc lại trạng thái sau khi có khóa
            run = peek
            if (
                run.status is not ScrapeStatus.NEEDS_HUMAN
                or run.challenge is None
                or moment - run.started_at >= NEEDS_HUMAN_STALE_AFTER
            ):
                raise ChallengeNotPending(details={"run_id": run_id, "status": run.status.value})
            if limit < run.pages_fetched + 1:
                raise InvalidScrapeRequest(
                    f"max_pages={limit} is below the page to resume from ({run.pages_fetched + 1})"
                )
            previous = runs.latest_succeeded(run.site, run.category)
            context = _RunContext(
                run_id=run_id,
                site=run.site,
                category=run.category,
                started_at=run.started_at,
                expect_items=previous is not None and previous.items_parsed > 0,
                previous_items=previous.items_parsed if previous is not None else None,
            )
            progress = _Progress(
                pages=run.pages_fetched,
                parsed=run.items_parsed,
                failed=run.items_failed,
                # Không biết lỗi trước khi dừng là loại nào: coi mọi lỗi cũ là không an toàn.
                unsafe=run.items_failed,
                upserted=run.offers_upserted,
                price_changes=run.price_changes,
            )
            challenge = Challenge.model_validate(run.challenge)
            runs.set_status(run, ScrapeStatus.RUNNING, now=moment)
            session.commit()
            return context, progress, challenge

    def _release_paused(self, run_id: int, challenge: Challenge) -> None:
        """Trả lượt về `NEEDS_HUMAN` (đáp án sai hoặc lỗi khi gửi đáp án)."""
        with self._session_factory() as session:
            runs = ScrapeRunRepository(session)
            run = _require_run(runs, run_id)
            runs.set_status(
                run,
                ScrapeStatus.NEEDS_HUMAN,
                challenge=challenge.model_dump(mode="json"),
                now=self._now(),
            )
            session.commit()

    # ---- vòng lặp thu thập ----
    async def _crawl(
        self,
        scraper: BaseScraper,
        context: _RunContext,
        progress: _Progress,
        *,
        start_page: int,
        max_pages: int,
    ) -> PipelineResult:
        error: str | None = None
        challenge: Challenge | None = None
        crashed = False
        page_number = start_page - 1
        try:
            async for page in scraper.crawl_category(
                context.category,
                max_pages,
                start_page=start_page,
                expect_items=context.expect_items,
            ):
                page_number += 1
                if not page.items and not page.skipped and page_number > 1:
                    # Trang sau trang đầu được trỏ tới bằng "Trang sau" mà trống: HTML lỗi hoặc chặn
                    # mềm, không phải hết danh mục. Dừng và không tắt offer nào.
                    error = (
                        f"Trang {page_number} trả về 200 nhưng không có sản phẩm "
                        "(nghi bị chặn mềm hoặc HTML lỗi)."
                    )
                    logger.warning("[run %s] %s", context.run_id, error)
                    break
                prepared = await self._prepare_items(scraper, page.items, progress)
                await asyncio.to_thread(
                    self._save_page, scraper.config, context, progress, prepared, page.skipped
                )
                progress.has_next = page.has_next
        except ChallengeDetected as detected:
            challenge = detected.challenge
        except FetchError as exc:
            error = _error_text(exc)
            logger.warning("[run %s] %s", context.run_id, error)
        except asyncio.CancelledError:
            # Task bị huỷ giữa lượt: đóng lượt lại thay vì để RUNNING tới khi quá hạn.
            await asyncio.shield(
                asyncio.to_thread(
                    self._finish, scraper, context, progress, None, "Lượt thu thập bị huỷ.", True
                )
            )
            raise
        except Exception as exc:
            crashed = True
            error = _error_text(exc)
            logger.exception("[run %s] lỗi không lường trước", context.run_id)
        return await asyncio.to_thread(
            self._finish, scraper, context, progress, challenge, error, crashed
        )

    async def _prepare_items(
        self, scraper: BaseScraper, items: Sequence[ListingItem], progress: _Progress
    ) -> list[tuple[ListingItem, ProductDetail | None]]:
        """Tải trang chi tiết cho mục thiếu thông số (trong giới hạn). Lỗi tải chi tiết không làm
        hỏng mục; challenge thì dừng cả lượt (ném `ChallengeDetected`)."""
        prepared: list[tuple[ListingItem, ProductDetail | None]] = []
        for item in items:
            detail: ProductDetail | None = None
            if not item.raw_specs and progress.detail_requests < self._max_detail_requests:
                progress.detail_requests += 1
                try:
                    detail = await scraper.fetch_detail(str(item.url))
                except (FetchError, ValueError) as exc:
                    logger.warning("Không tải được trang chi tiết (%s)", type(exc).__name__)
            prepared.append((item, detail))
        return prepared

    # ---- lưu một trang (chạy trong thread) ----
    def _save_page(
        self,
        config: SiteConfig,
        context: _RunContext,
        progress: _Progress,
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
                key = _url_key(item)
                if key is not None and key in seen:
                    continue  # cùng URL xuất hiện lại trong lượt: bản đầu tiên thắng
                if key is not None:
                    seen.add(key)
                try:
                    with session.begin_nested():
                        offer_id, price_changed = self._save_item(
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
            runs.update_counters(_require_run(runs, context.run_id), **totals)
            session.commit()
        progress.pages += 1
        progress.seen_urls = seen
        progress.parsed += parsed
        progress.failed += failed
        progress.unsafe += unsafe
        progress.upserted += upserted
        progress.price_changes += changes
        progress.changed_ids.extend(changed)

    def _save_item(
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
        _check_item_url(config, url)
        offers = OfferRepository(session)
        existing = offers.get_by_url(url)
        product_id = self._resolver(session, category, item, detail)

        # `upsert` ghi đè cả None/{}: gộp với dữ liệu đã có để lượt không tải chi tiết không xóa nó.
        raw_specs: dict[str, Any] = {}
        if existing is not None:
            raw_specs.update(existing.raw_specs)
        raw_specs.update(item.raw_specs)
        if detail is not None:
            raw_specs.update(detail.raw_specs)
        rating = item.rating if item.rating is not None else (existing.rating if existing else None)
        rating_count = (
            item.rating_count
            if item.rating_count is not None
            else (existing.rating_count if existing else None)
        )
        site_sku = item.site_sku or (existing.site_sku if existing else None)

        result = offers.upsert(
            OfferUpsert(
                product_id=product_id,
                site=item.site,
                url=url,
                title=item.title,
                price=item.price,
                list_price=item.list_price,
                price_type=item.price_type,
                stock_status=item.stock_status,
                site_sku=site_sku,
                rating=rating,
                rating_count=rating_count,
                raw_specs=raw_specs,
            ),
            now=moment,
        )
        snapshot = PriceHistoryRepository(session).record_snapshot(result.offer, now=moment)
        return _offer_id(result.offer), snapshot.price_changed

    # ---- kết thúc (chạy trong thread) ----
    def _finish(
        self,
        scraper: BaseScraper,
        context: _RunContext,
        progress: _Progress,
        challenge: Challenge | None,
        error: str | None,
        crashed: bool,
    ) -> PipelineResult:
        moment = self._now()
        verdict = self._decide(scraper, context, progress, challenge, error, crashed)
        status, message = verdict.status, verdict.message
        with self._session_factory() as session:
            runs = ScrapeRunRepository(session)
            run = _require_run(runs, context.run_id)
            runs.update_counters(
                run,
                pages_fetched=progress.pages,
                items_parsed=progress.parsed,
                items_failed=progress.failed,
                offers_upserted=progress.upserted,
                price_changes=progress.price_changes,
            )
            if verdict.deactivate:
                # Chỉ lượt đầy đủ và đáng tin mới được tắt offer không còn thấy (docs/06 §7).
                gone = OfferRepository(session).deactivate_unseen(
                    context.site, context.category, context.started_at
                )
                logger.info("[run %s] tắt %s offer không còn thấy", context.run_id, gone)
            challenge_json = challenge.model_dump(mode="json") if challenge is not None else None
            runs.set_status(
                run, status, error_message=message, challenge=challenge_json, now=moment
            )
            session.commit()
        logger.info(
            "[run %s] %s: %s trang, %s mục (%s lỗi), %s offer, %s đổi giá",
            context.run_id,
            status.value,
            progress.pages,
            progress.parsed,
            progress.failed,
            progress.upserted,
            progress.price_changes,
        )
        return PipelineResult(
            run_id=context.run_id,
            site=context.site,
            category=context.category,
            status=status,
            pages_fetched=progress.pages,
            items_parsed=progress.parsed,
            items_failed=progress.failed,
            offers_upserted=progress.upserted,
            price_changes=progress.price_changes,
            changed_offer_ids=tuple(progress.changed_ids),
            challenge=challenge,
            error_message=message,
        )

    @staticmethod
    def _decide(
        scraper: BaseScraper,
        context: _RunContext,
        progress: _Progress,
        challenge: Challenge | None,
        error: str | None,
        crashed: bool,
    ) -> _Verdict:
        if challenge is not None:
            # Chỉ mock-shop có luồng nhập đáp án, và chỉ cho captcha; mọi trường hợp khác là chặn.
            human = scraper.config.is_mock and challenge.kind is ChallengeKind.captcha
            return _Verdict(ScrapeStatus.NEEDS_HUMAN if human else ScrapeStatus.BLOCKED, None)
        if error is not None:
            if crashed or progress.pages == 0:
                return _Verdict(ScrapeStatus.FAILED, error)
            return _Verdict(ScrapeStatus.PARTIAL, error)
        warnings: list[str] = []
        ratio = progress.failed / progress.parsed if progress.parsed else 0.0
        if ratio > FAILED_RATIO_LIMIT:
            warnings.append(
                f"Cảnh báo chất lượng: {progress.failed}/{progress.parsed} mục lỗi "
                f"({ratio:.0%}), có thể trang đã đổi giao diện."
            )
        previous = context.previous_items
        dropped = bool(
            previous and progress.parsed < previous * DROP_RATIO_LIMIT and not progress.has_next
        )
        if dropped:
            warnings.append(
                f"Cảnh báo chất lượng: số sản phẩm giảm từ {previous} xuống {progress.parsed}."
            )
        if warnings:
            logger.warning("[run %s] %s", context.run_id, " ".join(warnings))
        capped = progress.has_next
        if ratio > FAILED_RATIO_LIMIT or capped:
            if capped:
                warnings.append("Dừng ở giới hạn số trang, chưa đủ danh mục.")
            return _Verdict(ScrapeStatus.PARTIAL, " ".join(warnings))
        # Không tắt offer khi: không thấy mục nào (có thể trang rỗng bất thường), số sản phẩm
        # giảm mạnh (trang đổi giao diện?) hoặc có mục lỗi mà lỗi đó không phải "hết giá".
        safe = progress.parsed > 0 and not dropped and progress.unsafe == 0
        return _Verdict(ScrapeStatus.SUCCEEDED, " ".join(warnings) or None, deactivate=safe)


def _require_id(run: ScrapeRun) -> int:
    if run.id is None:  # pragma: no cover - flush luôn gán id
        raise RuntimeError("scrape run has no id after flush")
    return run.id


def _offer_id(offer: Offer) -> int:
    if offer.id is None:  # pragma: no cover - upsert luôn trả offer đã lưu
        raise RuntimeError("offer has no id after upsert")
    return offer.id


def _require_run(runs: ScrapeRunRepository, run_id: int) -> ScrapeRun:
    run = runs.get(run_id)
    if run is None:
        raise RunNotFound(details={"run_id": run_id})
    return run
