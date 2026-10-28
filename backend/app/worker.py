"""Worker: lịch thu thập định kỳ bằng APScheduler (docs/03 §5.2, docs/10 §3).

Chạy `uv run python -m app.worker` (`make worker`). Hai job, đều chạy qua `ScrapeService` (pipeline
rồi đánh giá cảnh báo giá), múi giờ UTC:

- `catalog_refresh` (`CATALOG_REFRESH_CRON`): thu thập đầy đủ từng nhóm của từng trang đang bật.
- `tracked_refresh` (`TRACKED_REFRESH_CRON`): chỉ tải trang chi tiết của offer đang được theo dõi.

`SCHEDULER_ENABLED=false` (mặc định) thì worker thoát ngay, không thu thập gì. Trang thật chỉ được
chạy khi người dùng tự đặt `SCRAPER_OFFLINE_ONLY=false`; ở chế độ ngoại tuyến chỉ có mock-shop.
Mỗi (site, nhóm) chỉ một lượt tại một thời điểm (khóa của pipeline), nên hai job chồng nhau sẽ bỏ
qua nhóm đang chạy thay vì chạy trùng.
"""

import asyncio
import contextlib
import io
import logging
import re
import signal
import sys
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.agent.spec_filler import build_spec_filler
from app.config import Settings, get_settings
from app.domain.enums import ScrapeTrigger, SiteKey
from app.domain.errors import AppError, SiteCooldown
from app.scrapers.pipeline import PipelineResult
from app.scrapers.registry import SCRAPERS, SiteNotAvailable
from app.services.alert_evaluation import AlertEvaluator
from app.services.live_search_service import LiveSearchService
from app.services.scrape_runtime import ScrapeRuntime
from app.services.scrape_service import ScrapeService

logger = logging.getLogger("worker")

CATALOG_JOB_ID = "catalog_refresh"
TRACKED_JOB_ID = "tracked_refresh"
CANCEL_WAIT_SECONDS = 30  # chờ job đóng lượt khi tắt worker
MISFIRE_GRACE_SECONDS = 300  # bù lượt lỡ do tiến trình bận hoặc vừa khởi động lại trong 5 phút


_WEEKDAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")  # crontab: 0 và 7 = Chủ nhật
_NUMERIC_WEEKDAYS = re.compile(r"^[\d,\-/*]+$")
_WEEKDAY_ITEM = re.compile(r"^(\*|\d+)(?:-(\d+))?(?:/(\d+))?$")


def _weekday_names(field: str) -> str:
    """Trường thứ trong tuần của crontab dạng số → tên ngày ("1-5" → "mon,tue,wed,thu,fri").

    APScheduler đánh số 0 = thứ Hai, lệch với crontab (0/7 = Chủ nhật, 1 = thứ Hai), nên số được
    đổi sang tên ngày để `0 3 * * 1` chạy đúng thứ Hai. Trường chỉ có `*` giữ nguyên.
    """
    if field == "*":
        return field
    days: set[int] = set()
    for item in field.split(","):
        match = _WEEKDAY_ITEM.match(item)
        if match is None:
            raise ValueError(f"thứ trong tuần {item!r} không hợp lệ")
        first, last, step = match.groups()
        if first == "*":
            if last is not None:
                raise ValueError(f"thứ trong tuần {item!r} không hợp lệ")
            low, high = 0, 6
        else:
            low = int(first)
            high = int(last) if last is not None else (6 if step is not None else low)
        if not (0 <= low <= 7 and 0 <= high <= 7 and low <= high) or step == "0":
            raise ValueError(f"thứ trong tuần {item!r} nằm ngoài 0..7 hoặc khoảng bị ngược")
        days.update(day % 7 for day in range(low, high + 1, int(step or 1)))
    return ",".join(_WEEKDAY_NAMES[day] for day in sorted(days))


def _crontab_with_weekday_names(expression: str) -> str:
    fields = expression.split()
    if len(fields) == 5 and _NUMERIC_WEEKDAYS.match(fields[4]):
        fields[4] = _weekday_names(fields[4])
    return " ".join(fields)


def parse_cron(name: str, expression: str) -> CronTrigger:
    """Crontab 5 trường (UTC) → trigger; sai (hoặc không bao giờ chạy) thì ném `ValueError` nêu tên
    biến cấu hình. Thứ trong tuần theo chuẩn crontab (0/7 = Chủ nhật, 1 = thứ Hai)."""
    try:
        trigger = CronTrigger.from_crontab(
            _crontab_with_weekday_names(expression.strip()), timezone=UTC
        )
    except ValueError as error:
        raise ValueError(f"{name} không hợp lệ ({expression!r}): {error}") from None
    if trigger.get_next_fire_time(None, datetime.now(UTC)) is None:
        # Ngày không tồn tại (31 tháng 2...): hợp lệ về cú pháp nhưng job không bao giờ chạy
        # (BUG-M9-3); báo ngay lúc khởi động thay vì im lặng không thu thập gì.
        raise ValueError(f"{name} không hợp lệ ({expression!r}): lịch không bao giờ chạy")
    return trigger


class ScheduledJobs:
    """Hai việc định kỳ; mỗi lỗi của một trang/nhóm chỉ được ghi log, không làm hỏng job."""

    def __init__(
        self,
        service: ScrapeService,
        settings: Settings,
        evaluator: AlertEvaluator | None = None,
        live_search: LiveSearchService | None = None,
    ) -> None:
        self._service = service
        self._settings = settings
        self._evaluator = evaluator
        self._live_search = live_search  # dọn cache tầng 2 cũ sau mỗi lượt làm mới danh mục
        self._running: set[asyncio.Task[Any]] = set()

    def sites(self) -> list[SiteKey]:
        """Trang đang bật; ở chế độ ngoại tuyến chỉ còn mock-shop."""
        return [
            site
            for site, scraper in SCRAPERS.items()
            if scraper.config.enabled
            and (scraper.config.is_mock or not self._settings.scraper_offline_only)
        ]

    async def refresh_catalog(self) -> list[PipelineResult]:
        """Thu thập đầy đủ mọi nhóm của mọi trang; các trang chạy song song, nhóm chạy tuần tự."""
        with self._track_current_task():
            sites = self.sites()
            logger.info(
                "làm mới danh mục: %s", ", ".join(site.value for site in sites) or "(không có)"
            )
            per_site = await asyncio.gather(*(self._catalog_site(site) for site in sites))
            await self._sweep_alerts()
            await self._purge_live_cache()
            return [result for results in per_site for result in results]

    async def refresh_tracked(self) -> list[PipelineResult]:
        """Làm mới giá offer đang được theo dõi của mọi trang (song song giữa các trang)."""
        with self._track_current_task():
            sites = self.sites()
            logger.info(
                "làm mới giá theo dõi: %s", ", ".join(site.value for site in sites) or "(không có)"
            )
            per_site = await asyncio.gather(*(self._tracked_site(site) for site in sites))
            await self._sweep_alerts()
            return [result for results in per_site for result in results]

    async def cancel_running(self) -> None:
        """Hủy các job đang chạy và chờ chúng đóng lượt thu thập (`ScrapeRun` ghi "bị huỷ") tối đa
        `CANCEL_WAIT_SECONDS`. Gọi trước khi đóng Fetcher để không cắt request đang bay."""
        tasks = list(self._running)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=CANCEL_WAIT_SECONDS)

    @contextlib.contextmanager
    def _track_current_task(self) -> Iterator[None]:
        task = asyncio.current_task()
        if task is not None:
            self._running.add(task)
        try:
            yield
        finally:
            if task is not None:
                self._running.discard(task)

    async def _sweep_alerts(self) -> None:
        """Quét mọi cảnh báo còn hiệu lực sau job: bắt cảnh báo gửi lỗi lần trước và các thay đổi
        mà `changed_offer_ids` không có (offer mới, đổi tồn kho, đổi loại giá)."""
        if self._evaluator is None:
            return
        try:
            await self._evaluator.evaluate(None)
        except Exception:
            logger.exception("lỗi khi quét lại cảnh báo giá sau job")

    async def _purge_live_cache(self) -> None:
        """Xóa cache tìm kiếm tầng 2 đã hết hạn (bảng chỉ tăng nếu không ai dọn, T10.4a)."""
        if self._live_search is None:
            return
        try:
            removed = await self._live_search.purge_expired()
        except Exception:
            logger.exception("lỗi khi dọn cache tìm kiếm trực tiếp")
            return
        if removed:
            logger.info("đã xóa %s mục cache tìm kiếm trực tiếp hết hạn", removed)

    async def _catalog_site(self, site: SiteKey) -> list[PipelineResult]:
        results: list[PipelineResult] = []
        for category in SCRAPERS[site].config.categories:
            try:
                results.append(
                    await self._service.run(site, category, trigger=ScrapeTrigger.schedule)
                )
            except SiteCooldown:
                logger.warning("%s đang nghỉ sau khi bị chặn, bỏ qua các nhóm còn lại", site.value)
                break
            except (AppError, SiteNotAvailable) as error:
                logger.info("bỏ qua %s/%s: %s", site.value, category.value, error)
            except Exception:
                logger.exception("lỗi không lường trước khi thu thập %s/%s", site.value, category)
        return results

    async def _tracked_site(self, site: SiteKey) -> list[PipelineResult]:
        try:
            return await self._service.refresh_tracked(site)
        except (AppError, SiteNotAvailable) as error:
            logger.info("bỏ qua làm mới giá %s: %s", site.value, error)
        except Exception:
            logger.exception("lỗi không lường trước khi làm mới giá %s", site.value)
        return []


def build_scheduler(
    jobs: ScheduledJobs, settings: Settings, scheduler: AsyncIOScheduler | None = None
) -> AsyncIOScheduler:
    """Thêm hai job vào `scheduler` (tạo mới nếu không truyền); chưa `start()`.

    Cron sai ném `ValueError` ngay tại đây (lúc khởi động), không đợi tới giờ chạy.
    """
    scheduler = scheduler or AsyncIOScheduler(timezone=UTC)
    definitions: list[tuple[str, str, str, Callable[[], Awaitable[list[PipelineResult]]]]] = [
        (
            CATALOG_JOB_ID,
            "CATALOG_REFRESH_CRON",
            settings.catalog_refresh_cron,
            jobs.refresh_catalog,
        ),
        (
            TRACKED_JOB_ID,
            "TRACKED_REFRESH_CRON",
            settings.tracked_refresh_cron,
            jobs.refresh_tracked,
        ),
    ]
    for job_id, variable, expression, function in definitions:
        scheduler.add_job(
            function,
            parse_cron(variable, expression),
            id=job_id,
            name=job_id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
            replace_existing=True,
        )
    return scheduler


async def run_worker(
    settings: Settings, stop: asyncio.Event, runtime: ScrapeRuntime | None = None
) -> int:
    """Chạy lịch tới khi `stop` được đặt. Trả mã thoát (0 cả khi lịch đang tắt)."""
    if not settings.scheduler_enabled:
        logger.warning(
            "SCHEDULER_ENABLED=false nên worker không chạy lịch nào. Đặt true trong .env."
        )
        return 0
    runtime = runtime or ScrapeRuntime.build(settings, build_spec_filler(settings))
    try:
        jobs = ScheduledJobs(
            runtime.service, settings, runtime.alert_evaluator, runtime.live_search
        )
        scheduler = build_scheduler(jobs, settings)
        scheduler.start()
        logger.info(
            "worker chạy: danh mục %r, theo dõi %r (UTC), ngoại tuyến=%s",
            settings.catalog_refresh_cron,
            settings.tracked_refresh_cron,
            settings.scraper_offline_only,
        )
        try:
            await stop.wait()
        finally:
            scheduler.shutdown(wait=False)
            await jobs.cancel_running()  # trước khi đóng Fetcher, tránh cắt request đang bay
    finally:
        await runtime.aclose()
    logger.info("worker đã dừng")
    return 0


async def _main() -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        # Windows không hỗ trợ add_signal_handler: ở đó Ctrl-C ném KeyboardInterrupt.
        with contextlib.suppress(NotImplementedError, ValueError, AttributeError):
            loop.add_signal_handler(getattr(signal, name), stop.set)
    try:
        return await run_worker(get_settings(), stop)
    except ValueError as error:  # cron sai
        logger.error("%s", error)
        return 2


def configure_logging() -> None:
    """UTF-8 cho stdout/stderr (console Windows mặc định cp1252 làm vỡ log tiếng Việt)."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def main() -> int:
    configure_logging()
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
