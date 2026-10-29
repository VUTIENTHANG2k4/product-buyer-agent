"""Vòng đời `ScrapeRun` (khóa, thời gian nghỉ, HITL, trạng thái cuối) cho `ScrapePipeline`."""

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import text

from app.db.models import ScrapeRun
from app.db.repositories import OfferRepository, ScrapeRunRepository
from app.domain.dto import Challenge
from app.domain.enums import Category, ChallengeKind, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import (
    ChallengeNotPending,
    InvalidScrapeRequest,
    RunNotFound,
    ScrapeAlreadyRunning,
    SiteCooldown,
)
from app.scrapers.base import BaseScraper
from app.scrapers.pipeline.state import (
    ACTIVE_STATUSES,
    BLOCK_COOLDOWN,
    CANCELLED_BY_USER,
    DROP_RATIO_LIMIT,
    FAILED_RATIO_LIMIT,
    NEEDS_HUMAN_STALE_AFTER,
    RUNNING_STALE_AFTER,
    PipelineResult,
    Progress,
    RunContext,
    SessionFactory,
    Verdict,
    require_run,
    require_run_id,
)

logger = logging.getLogger(__name__)


def lock_key(site: SiteKey, category: Category) -> int:
    digest = hashlib.sha256(f"scrape:{site}:{category}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class RunStore:
    """Vòng đời `ScrapeRun` trong CSDL: tạo dưới khóa (site, nhóm), chiếm/trả lượt `NEEDS_HUMAN`,
    hủy, chốt kết cục. Mọi hàm đồng bộ (chạy qua `asyncio.to_thread`), mỗi hàm một transaction.
    """

    def __init__(self, session_factory: SessionFactory, now: Callable[[], datetime]) -> None:
        self._session_factory = session_factory
        self._now = now

    def start_run(
        self,
        site: SiteKey,
        category: Category,
        trigger: ScrapeTrigger,
        is_mock: bool,
        *,
        partial_scope: bool = False,
    ) -> RunContext:
        moment = self._now()
        with self._session_factory() as session:
            # Khóa theo (site, category): hai lượt đồng thời không cùng vượt qua kiểm tra bên dưới.
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key(site, category)}
            )
            runs = ScrapeRunRepository(session)
            active = runs.latest(site, category)
            if active is not None and self.is_active(active, moment):
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
            # Lượt làm mới chỉ chạm vài offer: so với lượt đầy đủ sẽ luôn báo "số sản phẩm giảm".
            previous = None if partial_scope else runs.latest_succeeded(site, category)
            run = runs.create(site, category, trigger, now=moment)
            session.commit()
            return RunContext(
                run_id=require_run_id(run),
                site=site,
                category=category,
                started_at=moment,
                expect_items=previous is not None and previous.items_parsed > 0,
                previous_items=previous.items_parsed if previous is not None else None,
                partial_scope=partial_scope,
            )

    @staticmethod
    def is_active(run: ScrapeRun, moment: datetime) -> bool:
        if run.status not in ACTIVE_STATUSES:
            return False
        stale_after = (
            NEEDS_HUMAN_STALE_AFTER
            if run.status is ScrapeStatus.NEEDS_HUMAN
            else RUNNING_STALE_AFTER
        )
        return moment - run.started_at < stale_after

    def claim_paused(self, run_id: int, limit: int) -> tuple[RunContext, Progress, Challenge]:
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
                {"key": lock_key(peek.site, peek.category)},
            )
            session.refresh(peek)  # đọc lại trạng thái sau khi có khóa
            run = peek
            if (
                run.status is not ScrapeStatus.NEEDS_HUMAN
                or run.trigger
                is ScrapeTrigger.tracked_refresh  # không có trang danh sách để tiếp tục
                or run.challenge is None
                or moment - run.started_at >= NEEDS_HUMAN_STALE_AFTER
            ):
                raise ChallengeNotPending(details={"run_id": run_id, "status": run.status.value})
            if limit < run.pages_fetched + 1:
                raise InvalidScrapeRequest(
                    f"max_pages={limit} is below the page to resume from ({run.pages_fetched + 1})"
                )
            previous = runs.latest_succeeded(run.site, run.category)
            context = RunContext(
                run_id=run_id,
                site=run.site,
                category=run.category,
                started_at=run.started_at,
                expect_items=previous is not None and previous.items_parsed > 0,
                previous_items=previous.items_parsed if previous is not None else None,
            )
            progress = Progress(
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

    def release_paused(self, run_id: int, challenge: Challenge) -> None:
        """Trả lượt về `NEEDS_HUMAN` (đáp án sai hoặc lỗi khi gửi đáp án)."""
        with self._session_factory() as session:
            runs = ScrapeRunRepository(session)
            run = require_run(runs, run_id)
            runs.set_status(
                run,
                ScrapeStatus.NEEDS_HUMAN,
                challenge=challenge.model_dump(mode="json"),
                now=self._now(),
            )
            session.commit()

    def cancel_paused(self, run_id: int) -> None:
        with self._session_factory() as session:
            runs = ScrapeRunRepository(session)
            peek = runs.get(run_id)
            if peek is None:
                raise RunNotFound(details={"run_id": run_id})
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": lock_key(peek.site, peek.category)},
            )
            session.refresh(peek)  # đọc lại trạng thái sau khi có khóa (tranh với `resume`)
            if peek.status is not ScrapeStatus.NEEDS_HUMAN:
                raise ChallengeNotPending(details={"run_id": run_id, "status": peek.status.value})
            runs.set_status(
                peek, ScrapeStatus.FAILED, error_message=CANCELLED_BY_USER, now=self._now()
            )
            session.commit()
        logger.info("[run %s] đã hủy lượt đang chờ đáp án captcha", run_id)

    def finish(
        self,
        scraper: BaseScraper,
        context: RunContext,
        progress: Progress,
        challenge: Challenge | None,
        error: str | None,
        crashed: bool,
    ) -> PipelineResult:
        moment = self._now()
        verdict = self.decide(scraper, context, progress, challenge, error, crashed)
        status, message = verdict.status, verdict.message
        with self._session_factory() as session:
            runs = ScrapeRunRepository(session)
            run = require_run(runs, context.run_id)
            runs.update_counters(
                run,
                pages_fetched=progress.pages,
                items_parsed=progress.parsed,
                items_failed=progress.failed,
                offers_upserted=progress.upserted,
                price_changes=progress.price_changes,
            )
            if verdict.deactivate and not context.partial_scope:
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
    def decide(
        scraper: BaseScraper,
        context: RunContext,
        progress: Progress,
        challenge: Challenge | None,
        error: str | None,
        crashed: bool,
    ) -> Verdict:
        if challenge is not None:
            # Chỉ mock-shop có luồng nhập đáp án, và chỉ cho captcha; mọi trường hợp khác là chặn.
            # Lượt làm mới giá không có trang để tiếp tục: gặp captcha là dừng (BLOCKED), không chờ.
            human = (
                scraper.config.is_mock
                and challenge.kind is ChallengeKind.captcha
                and not context.partial_scope
            )
            return Verdict(ScrapeStatus.NEEDS_HUMAN if human else ScrapeStatus.BLOCKED, None)
        if error is not None:
            if crashed or progress.pages == 0:
                return Verdict(ScrapeStatus.FAILED, error)
            return Verdict(ScrapeStatus.PARTIAL, error)
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
            if progress.loop:
                warnings.append("Phân trang lặp lại URL đã tải, dừng; chưa đủ danh mục.")
            elif capped:
                warnings.append("Dừng ở giới hạn số trang, chưa đủ danh mục.")
            return Verdict(ScrapeStatus.PARTIAL, " ".join(warnings))
        # Không tắt offer khi: không thấy mục nào (có thể trang rỗng bất thường), số sản phẩm
        # giảm mạnh (trang đổi giao diện?) hoặc có mục lỗi mà lỗi đó không phải "hết giá".
        safe = progress.parsed > 0 and not dropped and progress.unsafe == 0
        return Verdict(ScrapeStatus.SUCCEEDED, " ".join(warnings) or None, deactivate=safe)
