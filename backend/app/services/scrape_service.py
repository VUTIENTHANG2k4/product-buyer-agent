"""Chạy thu thập: lớp duy nhất mà worker và router quản trị gọi (docs/03 §5.2, docs/06 §7).

Gọi pipeline rồi chuyển danh sách offer đổi giá cho bộ đánh giá cảnh báo. `alert_service` thuộc M9
nên bộ đánh giá là hook tiêm vào (`on_price_changes`); chưa có thì bỏ qua.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence

from app.config import Settings
from app.db.models import utc_now
from app.db.repositories import OfferRepository, ScrapeRunRepository
from app.domain.admin import ChallengeView
from app.domain.dto import Challenge
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import (
    ChallengeNotPending,
    InvalidScrapeRequest,
    OfflineMode,
    RunNotFound,
    ScrapeAlreadyRunning,
    SiteCooldown,
)
from app.normalize.llm_extract import LlmSpecsFiller
from app.scrapers.http.types import FormFetcher
from app.scrapers.pipeline import (
    NEEDS_HUMAN_STALE_AFTER,
    PipelineResult,
    ScrapePipeline,
    SessionFactory,
    StartedRun,
    make_resolver,
)
from app.scrapers.registry import SiteNotAvailable, get_scraper
from app.services.views import Clock, aware_now

logger = logging.getLogger(__name__)

PriceChangeHook = Callable[[Sequence[int]], Awaitable[None]]


class ScrapeService:
    def __init__(
        self,
        session_factory: SessionFactory,
        fetcher: FormFetcher,
        settings: Settings,
        *,
        on_price_changes: PriceChangeHook | None = None,
        pipeline: ScrapePipeline | None = None,
        spec_filler: LlmSpecsFiller | None = None,
        now: Clock = utc_now,
    ) -> None:
        """`spec_filler` (LLM dự phòng, T5.3) do nơi lắp ráp tiêm; bỏ qua nếu có `pipeline`."""
        self._session_factory = session_factory
        self._now = now
        self._settings = settings
        self._fetcher = fetcher
        self._on_price_changes = on_price_changes
        self._pipeline = pipeline or ScrapePipeline(
            session_factory,
            fetcher,
            default_max_pages=settings.scraper_max_listing_pages,
            resolver=make_resolver(spec_filler if settings.llm_extractor_enabled else None),
        )

    async def run(
        self,
        site: SiteKey,
        category: Category,
        *,
        trigger: ScrapeTrigger = ScrapeTrigger.manual,
        max_pages: int | None = None,
    ) -> PipelineResult:
        """Một lượt thu thập. `OfflineMode` nếu trang thật mà `SCRAPER_OFFLINE_ONLY=true`.

        Còn ném `SiteNotAvailable`, `SiteCooldown`, `ScrapeAlreadyRunning` từ phía dưới.
        """
        self._ensure_allowed(site)
        result = await self._pipeline.run(site, category, trigger, max_pages=max_pages)
        await self._evaluate(result)
        return result

    async def start(
        self,
        site: SiteKey,
        category: Category,
        *,
        trigger: ScrapeTrigger = ScrapeTrigger.manual,
        max_pages: int | None = None,
    ) -> StartedRun:
        """Tạo lượt (RUNNING) rồi trả ngay; nơi gọi `execute()` kết quả, thường ở tác vụ nền.

        Lỗi đồng bộ: `OfflineMode`, `SiteCooldown`, `ScrapeAlreadyRunning` và `InvalidScrapeRequest`
        (trang chưa có scraper/đã tắt, nhóm không thuộc trang, `max_pages` < 1).
        """
        try:
            self._ensure_allowed(site)
            return await self._pipeline.start(site, category, trigger, max_pages=max_pages)
        except SiteNotAvailable as error:
            raise InvalidScrapeRequest(f"Trang {site.value} chưa có scraper hoặc đã tắt") from error

    async def execute(self, started: StartedRun) -> PipelineResult:
        """Chạy lượt đã `start`/`reopen` rồi đánh giá cảnh báo cho các offer đổi giá."""
        result = await self._pipeline.execute(started)
        await self._evaluate(result)
        return result

    async def reopen(self, run_id: int, answer: str, *, max_pages: int | None = None) -> StartedRun:
        """Gửi đáp án captcha cho lượt `NEEDS_HUMAN` rồi trả lượt đã chiếm để `execute()`.

        Ném `RunNotFound`, `ChallengeNotPending`, `ChallengeFailed` (đáp án sai: lượt vẫn chờ).
        """
        return await self._pipeline.reopen(run_id, answer, max_pages=max_pages)

    async def cancel_challenge(self, run_id: int) -> None:
        """Hủy lượt đang chờ đáp án captcha (T2.8); `RunNotFound`/`ChallengeNotPending`."""
        await self._pipeline.cancel_paused(run_id)

    def challenge_of(self, run_id: int) -> ChallengeView:
        """Challenge của lượt đang chờ người nhập đáp án (không có `token`).

        `RunNotFound` nếu không có lượt; `ChallengeNotPending` nếu lượt không chờ đáp án hoặc đã
        quá hạn chờ (khi đó lượt mới được phép chạy).
        """
        with self._session_factory() as session:
            run = ScrapeRunRepository(session).get(run_id)
            if run is None:
                raise RunNotFound(details={"run_id": run_id})
            if (
                run.status is not ScrapeStatus.NEEDS_HUMAN
                or run.challenge is None
                or aware_now(self._now) - run.started_at >= NEEDS_HUMAN_STALE_AFTER
            ):
                raise ChallengeNotPending(details={"run_id": run_id, "status": run.status.value})
            challenge = Challenge.model_validate(run.challenge)
        return ChallengeView(
            kind=challenge.kind,
            prompt=challenge.prompt,
            image_url=None if challenge.image_url is None else str(challenge.image_url),
        )

    def _ensure_allowed(self, site: SiteKey) -> None:
        config = get_scraper(site, self._fetcher).config
        if self._settings.scraper_offline_only and not config.is_mock:
            raise OfflineMode(details={"site": site.value})

    async def refresh_tracked(self, site: SiteKey) -> list[PipelineResult]:
        """Làm mới giá các offer đang được theo dõi của `site` (cảnh báo còn hiệu lực hoặc có trong
        danh sách mua) rồi đánh giá cảnh báo; mỗi nhóm sản phẩm là một lượt `tracked_refresh`.

        Chỉ tải trang chi tiết của chính các offer đó. `OfflineMode` nếu trang thật mà
        `SCRAPER_OFFLINE_ONLY=true`. Một nhóm đang có lượt khác chạy (`ScrapeAlreadyRunning`) hoặc
        trang đang nghỉ sau khi bị chặn (`SiteCooldown`) thì bỏ qua phần còn lại và trả những lượt
        đã xong.
        """
        self._ensure_allowed(site)
        by_category: dict[Category, list[int]] = {}
        with self._session_factory() as session:
            for tracked in OfferRepository(session).list_tracked(site):
                by_category.setdefault(tracked.category, []).append(tracked.offer_id)
        results: list[PipelineResult] = []
        for category, offer_ids in by_category.items():
            if category not in get_scraper(site, self._fetcher).config.categories:
                continue
            try:
                result = await self._pipeline.refresh_offers(site, category, offer_ids)
            except (ScrapeAlreadyRunning, SiteCooldown) as error:
                logger.info("bỏ qua làm mới giá %s/%s: %s", site, category, error.code)
                if isinstance(error, SiteCooldown):
                    break
                continue
            except Exception:
                # Lỗi bất ngờ của một nhóm (mất kết nối CSDL khi tạo lượt...) không được làm mất các
                # nhóm còn lại, như job `catalog_refresh` (BUG-M9-8).
                logger.exception("lỗi không lường trước khi làm mới giá %s/%s", site, category)
                continue
            await self._evaluate(result)
            results.append(result)
        return results

    async def resume(
        self, run_id: int, answer: str, *, max_pages: int | None = None
    ) -> PipelineResult:
        """Nhập đáp án captcha cho lượt `NEEDS_HUMAN` (mock-shop) và chạy tiếp."""
        result = await self._pipeline.resume(run_id, answer, max_pages=max_pages)
        await self._evaluate(result)
        return result

    async def _evaluate(self, result: PipelineResult) -> None:
        if self._on_price_changes is None or not result.changed_offer_ids:
            return
        try:
            await self._on_price_changes(result.changed_offer_ids)
        except Exception:
            # Lỗi đánh giá cảnh báo không được làm mất kết quả thu thập đã lưu.
            logger.exception("[run %s] đánh giá cảnh báo giá thất bại", result.run_id)
