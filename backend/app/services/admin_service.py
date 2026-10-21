"""Đọc thông tin quản trị thu thập: nguồn, lượt chạy (docs/07 §3.6).

Chỉ đọc. Việc chạy thu thập và nhập đáp án challenge thuộc `scrape_service`. Dịch vụ này đọc
`SiteConfig` từ registry và hằng số thời gian nghỉ của pipeline, không gọi pipeline hay mạng.
"""

from collections.abc import Callable
from datetime import datetime

from sqlmodel import Session

from app.config import Settings
from app.db.models import ScrapeRun, utc_now
from app.db.repositories import ScrapeRunRepository
from app.domain.admin import ScrapeRunView, SourceView
from app.domain.enums import Category, ChallengeKind, ScrapeStatus, SiteKey
from app.domain.errors import RunNotFound
from app.scrapers.http.robots import RobotsSnapshot
from app.scrapers.pipeline import BLOCK_COOLDOWN
from app.scrapers.registry import SCRAPERS
from app.services.views import Clock, aware_now

RobotsLookup = Callable[[str], RobotsSnapshot | None]
"""URL gốc của trang → tóm tắt robots.txt đã tải (None nếu chưa tải)."""


def to_run_view(run: ScrapeRun) -> ScrapeRunView:
    if run.id is None:  # pragma: no cover - lượt đọc từ CSDL luôn có id
        raise RuntimeError("scrape run has no id")
    kind = run.challenge.get("kind") if run.challenge else None
    return ScrapeRunView(
        run_id=run.id,
        site=run.site,
        category=run.category,
        status=run.status,
        trigger=run.trigger,
        pages_fetched=run.pages_fetched,
        items_parsed=run.items_parsed,
        items_failed=run.items_failed,
        offers_upserted=run.offers_upserted,
        price_changes=run.price_changes,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_message=run.error_message,
        challenge_kind=ChallengeKind(kind) if kind else None,
    )


class AdminService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        robots: RobotsLookup | None = None,
        now: Clock = utc_now,
    ) -> None:
        self._settings = settings
        self._robots = robots or (lambda url: None)
        self._now = now
        self._runs = ScrapeRunRepository(session)

    def sources(self) -> list[SourceView]:
        """Mọi trang đã đăng ký scraper, theo thứ tự `SiteKey`."""
        moment = aware_now(self._now)
        views: list[SourceView] = []
        for site in SiteKey:
            scraper = SCRAPERS.get(site)
            if scraper is None:
                continue
            config = scraper.config
            robots = None if config.is_mock else self._robots(config.base_url)
            recent = self._runs.list_recent(site=site, limit=1)
            views.append(
                SourceView(
                    key=site,
                    enabled=config.enabled,
                    is_mock=config.is_mock,
                    categories=[category for category in Category if category in config.categories],
                    # Mock-shop không có robots.txt đáng kể: luôn được phép.
                    robots_status="allowed"
                    if config.is_mock
                    else (robots.status if robots else "unknown"),
                    effective_delay_s=self._delay(config.is_mock, config.min_delay_s, robots),
                    supports_live_search=config.supports_live_search,
                    last_run=to_run_view(recent[0]) if recent else None,
                    cooldown_until=None if config.is_mock else self._cooldown_until(site, moment),
                )
            )
        return views

    def list_runs(
        self,
        *,
        site: SiteKey | None = None,
        category: Category | None = None,
        status: ScrapeStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ScrapeRunView], int]:
        """Một trang lượt chạy (mới nhất trước) và tổng số lượt khớp."""
        runs, total = self._runs.list_filtered(
            site=site,
            category=category,
            status=status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [to_run_view(run) for run in runs], total

    def get_run(self, run_id: int) -> ScrapeRunView:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(details={"run_id": run_id})
        return to_run_view(run)

    def _delay(self, is_mock: bool, site_delay: float, robots: RobotsSnapshot | None) -> float:
        """Độ trễ giữa hai request: lớn nhất của env, `Crawl-delay` đã biết và cấu hình trang."""
        if is_mock:
            return float(self._settings.mock_shop_delay_seconds)
        crawl = robots.crawl_delay if robots and robots.crawl_delay is not None else 0.0
        return max(float(self._settings.scraper_min_delay_seconds), site_delay, crawl)

    def _cooldown_until(self, site: SiteKey, moment: datetime) -> datetime | None:
        blocked = self._runs.latest_blocked_since(site, moment - BLOCK_COOLDOWN)
        if blocked is None:
            return None
        until = blocked.started_at + BLOCK_COOLDOWN
        return until if until > moment else None
