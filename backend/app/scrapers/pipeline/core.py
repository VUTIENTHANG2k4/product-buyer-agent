"""`ScrapePipeline`: điều phối một lượt thu thập (tải trang qua scraper, lưu qua `OfferWriter`,
vòng đời qua `RunStore`) và lượt làm mới giá offer đang theo dõi (docs/06 §7)."""

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.domain.clock import utc_now
from app.domain.dto import Challenge, ListingItem, ProductDetail
from app.domain.enums import Category, ScrapeTrigger, SiteKey
from app.domain.errors import ChallengeFailed, InvalidScrapeRequest
from app.scrapers.base import BaseScraper
from app.scrapers.challenge import ChallengeDetected, robots_block_challenge
from app.scrapers.http.errors import FetchError, FetchFailed, HttpStatusError, RobotsBlocked
from app.scrapers.http.types import FormFetcher
from app.scrapers.pipeline.resolve import ProductResolver, resolve_product
from app.scrapers.pipeline.run_store import RunStore
from app.scrapers.pipeline.state import (
    DEFAULT_MAX_DETAIL_REQUESTS,
    GONE_STATUSES,
    MAX_CONSECUTIVE_REFRESH_FAILURES,
    PipelineResult,
    Progress,
    RunContext,
    SessionFactory,
    StartedRun,
)
from app.scrapers.pipeline.writer import OfferWriter
from app.scrapers.registry import get_scraper

logger = logging.getLogger(__name__)


class ScrapePipeline:
    def __init__(
        self,
        session_factory: SessionFactory,
        fetcher: FormFetcher,
        *,
        default_max_pages: int = 3,
        max_detail_requests: int = DEFAULT_MAX_DETAIL_REQUESTS,
        resolver: ProductResolver = resolve_product,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._fetcher = fetcher
        self._default_max_pages = default_max_pages
        self._max_detail_requests = max_detail_requests
        self._runs = RunStore(session_factory, now)
        self._writer = OfferWriter(session_factory, now, resolver)

    # ---- API ----
    async def run(
        self,
        site: SiteKey,
        category: Category,
        trigger: ScrapeTrigger,
        *,
        max_pages: int | None = None,
    ) -> PipelineResult:
        """Một lượt thu thập (site, category): `start` rồi `execute`.

        Ném `SiteNotAvailable` (trang chưa đăng ký/đã tắt), `SiteCooldown` (trang thật vừa chặn)
        hoặc `ScrapeAlreadyRunning`. Mọi kết cục khác (lỗi tải, challenge, lỗi không lường
        trước) được ghi vào `ScrapeRun` và trả về trong kết quả thay vì ném ra.
        """
        return await self.execute(await self.start(site, category, trigger, max_pages=max_pages))

    async def start(
        self,
        site: SiteKey,
        category: Category,
        trigger: ScrapeTrigger,
        *,
        max_pages: int | None = None,
    ) -> StartedRun:
        """Kiểm tra điều kiện và tạo `ScrapeRun` (RUNNING) nhưng chưa tải trang nào.

        Lỗi đồng bộ như `run()`. Nơi gọi PHẢI `execute()` kết quả (hoặc để lượt quá hạn sau
        `RUNNING_STALE_AFTER`); API dùng để trả `run_id` ngay rồi chạy nền.
        """
        scraper = get_scraper(site, self._fetcher)
        if category not in scraper.config.categories:
            raise InvalidScrapeRequest(f"{site} has no category {category}")
        limit = self._limit(max_pages)
        context = await asyncio.to_thread(
            self._runs.start_run, site, category, trigger, scraper.config.is_mock
        )
        logger.info(
            "[run %s] bắt đầu %s/%s (tối đa %s trang)", context.run_id, site, category, limit
        )
        return StartedRun(scraper, context, Progress(), start_page=1, max_pages=limit)

    async def execute(self, started: StartedRun) -> PipelineResult:
        """Chạy vòng thu thập của lượt đã `start`/`reopen` tới khi xong, bị chặn hoặc cần người.

        Mỗi `StartedRun` chỉ chạy một lần: lần hai ném `RuntimeError` (lượt đã được chạy hoặc đã
        bị `abandon`).
        """
        if started.lifecycle.claimed:
            raise RuntimeError(f"lượt {started.run_id} đã được chạy hoặc đã bị huỷ")
        started.lifecycle.claimed = True
        return await self._crawl(
            started.scraper,
            started.context,
            started.progress,
            start_page=started.start_page,
            max_pages=started.max_pages,
        )

    async def abandon(self, started: StartedRun) -> None:
        """Chốt `FAILED` cho lượt đã `start`/`reopen` mà `execute` không bao giờ chạy (task bị hủy
        trước khi bắt đầu, ví dụ tắt app ngay sau 202); nếu không lượt kẹt `RUNNING` tới 2 giờ và
        chặn lượt mới. Không làm gì nếu `execute` đã nhận lượt (nó tự chốt khi bị hủy)."""
        if started.lifecycle.claimed:
            return
        started.lifecycle.claimed = True
        await self._finish_cancelled(started.scraper, started.context, started.progress)

    async def resume(
        self, run_id: int, answer: str, *, max_pages: int | None = None
    ) -> PipelineResult:
        """`reopen` rồi `execute`: gửi đáp án captcha của mock-shop và tiếp tục lượt `NEEDS_HUMAN`.

        Ném `RunNotFound`, `ChallengeNotPending` (lượt không chờ đáp án) hoặc `ChallengeFailed` (đáp
        án sai: lượt vẫn `NEEDS_HUMAN`, thử lại được). Phải dùng cùng `Fetcher` với lượt đầu nếu
        muốn giữ cookie phiên; một tiến trình mới vẫn được vì cookie lấy lại từ chính lần gửi này.
        """
        return await self.execute(await self.reopen(run_id, answer, max_pages=max_pages))

    async def reopen(self, run_id: int, answer: str, *, max_pages: int | None = None) -> StartedRun:
        """Chiếm lượt `NEEDS_HUMAN` và gửi đáp án; đúng thì trả lượt (RUNNING) để `execute` tiếp.

        Lỗi đồng bộ như `resume()`. Lượt đang RUNNING sau khi trả về: nơi gọi phải `execute()`.
        """
        limit = self._limit(max_pages)
        context, progress, challenge = await asyncio.to_thread(
            self._runs.claim_paused, run_id, limit
        )
        scraper = get_scraper(context.site, self._fetcher)
        try:
            url, data = scraper.challenge_submission(challenge, answer)
            response = await self._fetcher.post_form(url, data)
            if response.status >= 400 and response.status != 400:
                raise FetchFailed(f"challenge endpoint returned HTTP {response.status}", url=url)
        except BaseException:
            # Lượt đã chuyển sang RUNNING để chặn resume đồng thời: trả lại để thử đáp án khác.
            await asyncio.shield(asyncio.to_thread(self._runs.release_paused, run_id, challenge))
            raise
        if response.status == 400:
            await asyncio.to_thread(self._runs.release_paused, run_id, challenge)
            raise ChallengeFailed()
        logger.info("[run %s] đáp án đúng, tiếp tục từ trang %s", run_id, progress.pages + 1)
        return StartedRun(
            scraper, context, progress, start_page=progress.pages + 1, max_pages=limit
        )

    async def cancel_paused(self, run_id: int) -> None:
        """Hủy lượt `NEEDS_HUMAN`: đóng thành `FAILED` ("Đã hủy bởi người dùng") để lượt mới chạy
        ngay thay vì chờ `NEEDS_HUMAN_STALE_AFTER`, hoặc khi mock-shop đã reset nên đáp án không
        bao giờ đúng (T2.8). Ném `RunNotFound` hoặc `ChallengeNotPending` (lượt không chờ đáp án,
        kể cả đã bị hủy/chiếm bởi `resume`)."""
        await asyncio.to_thread(self._runs.cancel_paused, run_id)

    async def refresh_offers(
        self,
        site: SiteKey,
        category: Category,
        offer_ids: Sequence[int],
        *,
        trigger: ScrapeTrigger = ScrapeTrigger.tracked_refresh,
    ) -> PipelineResult:
        """Làm mới giá của các offer đang được theo dõi bằng đúng trang chi tiết của chúng.

        Chỉ tải `offer.url` (qua Fetcher), ghi `price`/`stock_status` và lịch sử giá; `list_price`
        và `price_type` chỉ đổi khi trang cho biết (`price_type != unknown`). Không tắt offer nào,
        kể cả khi trang trả 404. Dùng khóa và thời gian nghỉ của (site, category) như lượt đầy
        đủ nên không chạy cùng lúc với lượt đầy đủ của nhóm đó. Ném `ScrapeAlreadyRunning`,
        `SiteCooldown`, `InvalidScrapeRequest` (nhóm không thuộc trang) như `start`; kết cục khác
        nằm trong kết quả.
        """
        scraper = get_scraper(site, self._fetcher)
        if category not in scraper.config.categories:
            raise InvalidScrapeRequest(f"{site} has no category {category}")
        context = await asyncio.to_thread(
            self._runs.start_run,
            site,
            category,
            trigger,
            scraper.config.is_mock,
            partial_scope=True,
        )
        logger.info(
            "[run %s] làm mới giá %s offer của %s/%s",
            context.run_id,
            len(offer_ids),
            site,
            category,
        )
        progress = Progress()
        challenge: Challenge | None = None
        error: str | None = None
        crashed = False
        try:
            targets = await asyncio.to_thread(
                self._writer.refresh_targets, site, category, offer_ids
            )
            error = await self._refresh_loop(scraper, context, progress, targets)
        except ChallengeDetected as detected:
            challenge = detected.challenge
        except RobotsBlocked as blocked:
            challenge = robots_block_challenge(context.site, blocked.url, blocked.status)
            logger.warning("[run %s] robots.txt bị chặn (HTTP %s)", context.run_id, blocked.status)
        except asyncio.CancelledError:
            await self._finish_cancelled(scraper, context, progress)
            raise
        except Exception as exc:
            crashed = True
            error = _error_text(exc)
            logger.exception("[run %s] lỗi không lường trước", context.run_id)
        return await asyncio.to_thread(
            self._runs.finish, scraper, context, progress, challenge, error, crashed
        )

    async def _refresh_loop(
        self,
        scraper: BaseScraper,
        context: RunContext,
        progress: Progress,
        targets: list[tuple[int, str]],
    ) -> str | None:
        """Tải từng trang chi tiết rồi lưu giá; trả thông điệp lỗi nếu phải dừng sớm."""
        consecutive = 0
        for offer_id, url in targets:
            progress.parsed += 1
            try:
                detail = await scraper.fetch_detail(url)
            except (ChallengeDetected, RobotsBlocked):
                raise  # trang chặn ta: dừng cả lượt như lượt đầy đủ
            except (FetchError, ValueError) as exc:
                progress.failed += 1
                progress.unsafe += 1
                gone = isinstance(exc, HttpStatusError) and exc.status in GONE_STATUSES
                consecutive = 0 if gone else consecutive + 1
                logger.warning(
                    "[run %s] không tải được offer %s (%s)",
                    context.run_id,
                    offer_id,
                    type(exc).__name__,
                )
                if consecutive >= MAX_CONSECUTIVE_REFRESH_FAILURES:
                    return f"{consecutive} lần tải liên tiếp thất bại, dừng lượt làm mới giá."
                continue
            consecutive = 0
            progress.pages += 1
            if detail.price is None:
                progress.failed += 1  # giá bị che/không đọc được: giữ giá cũ, không phải lỗi trang
                continue
            try:
                changed = await asyncio.to_thread(self._writer.save_refresh, offer_id, detail)
            except (ValueError, ValidationError, SQLAlchemyError) as exc:
                progress.failed += 1
                progress.unsafe += 1
                logger.warning(
                    "[run %s] không lưu được offer %s (%s)",
                    context.run_id,
                    offer_id,
                    type(exc).__name__,
                )
                continue
            progress.upserted += 1
            if changed:
                progress.price_changes += 1
                progress.changed_ids.append(offer_id)
        return None

    async def _finish_cancelled(
        self, scraper: BaseScraper, context: RunContext, progress: Progress
    ) -> None:
        """Chốt `FAILED` cho lượt bị hủy; `shield` để chính lệnh hủy không cắt ngang việc chốt."""
        await asyncio.shield(
            asyncio.to_thread(
                self._runs.finish, scraper, context, progress, None, "Lượt thu thập bị huỷ.", True
            )
        )

    def _limit(self, max_pages: int | None) -> int:
        limit = max_pages if max_pages is not None else self._default_max_pages
        if limit < 1:
            raise InvalidScrapeRequest(f"max_pages must be >= 1, got {limit}")
        return limit

    # ---- vòng lặp thu thập ----
    async def _crawl(
        self,
        scraper: BaseScraper,
        context: RunContext,
        progress: Progress,
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
                    self._writer.save_page,
                    scraper.config,
                    context,
                    progress,
                    prepared,
                    page.skipped,
                )
                progress.has_next = page.has_next
                progress.loop = page.pagination_loop
        except ChallengeDetected as detected:
            challenge = detected.challenge
        except RobotsBlocked as blocked:
            challenge = robots_block_challenge(context.site, blocked.url, blocked.status)
            logger.warning("[run %s] robots.txt bị chặn (HTTP %s)", context.run_id, blocked.status)
        except FetchError as exc:
            error = _error_text(exc)
            logger.warning("[run %s] %s", context.run_id, error)
        except asyncio.CancelledError:
            # Task bị huỷ giữa lượt: đóng lượt lại thay vì để RUNNING tới khi quá hạn.
            await self._finish_cancelled(scraper, context, progress)
            raise
        except Exception as exc:
            crashed = True
            error = _error_text(exc)
            logger.exception("[run %s] lỗi không lường trước", context.run_id)
        return await asyncio.to_thread(
            self._runs.finish, scraper, context, progress, challenge, error, crashed
        )

    async def _prepare_items(
        self, scraper: BaseScraper, items: Sequence[ListingItem], progress: Progress
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
                except RobotsBlocked:
                    raise  # robots.txt hết hạn giữa lượt và bị chặn: dừng cả lượt như challenge
                except (FetchError, ValueError) as exc:
                    logger.warning("Không tải được trang chi tiết (%s)", type(exc).__name__)
            prepared.append((item, detail))
        return prepared


def _error_text(exc: BaseException) -> str:
    """Thông điệp cho `ScrapeRun.error_message`: lỗi tải có URL công khai, lỗi khác chỉ lấy tên."""
    if isinstance(exc, FetchError):
        return f"{type(exc).__name__}: {exc}"[:500]
    return f"Lỗi không lường trước: {type(exc).__name__}"
