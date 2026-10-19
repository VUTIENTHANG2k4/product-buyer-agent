"""Chạy thu thập: lớp duy nhất mà worker và router quản trị gọi (docs/03 §5.2, docs/06 §7).

Gọi pipeline rồi chuyển danh sách offer đổi giá cho bộ đánh giá cảnh báo. `alert_service` thuộc M9
nên bộ đánh giá là hook tiêm vào (`on_price_changes`); chưa có thì bỏ qua.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence

from app.config import Settings
from app.domain.enums import Category, ScrapeTrigger, SiteKey
from app.domain.errors import OfflineMode
from app.scrapers.http.types import FormFetcher
from app.scrapers.pipeline import PipelineResult, ScrapePipeline, SessionFactory
from app.scrapers.registry import get_scraper

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
    ) -> None:
        self._settings = settings
        self._fetcher = fetcher
        self._on_price_changes = on_price_changes
        self._pipeline = pipeline or ScrapePipeline(
            session_factory, fetcher, default_max_pages=settings.scraper_max_listing_pages
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
        config = get_scraper(site, self._fetcher).config
        if self._settings.scraper_offline_only and not config.is_mock:
            raise OfflineMode(details={"site": site.value})
        result = await self._pipeline.run(site, category, trigger, max_pages=max_pages)
        await self._evaluate(result)
        return result

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
