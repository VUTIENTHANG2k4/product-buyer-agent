"""Repository cho `ScrapeRun`: vòng đời một lượt thu thập và truy vấn lượt gần nhất."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func
from sqlmodel import Session, col, select

from app.db.models import ScrapeRun, utc_now
from app.db.repositories.ids import fits_int4
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey

# Trạng thái kết thúc: có `finished_at`. `NEEDS_HUMAN` chưa kết thúc (chờ `resume`).
FINISHED_STATUSES = frozenset(
    {ScrapeStatus.SUCCEEDED, ScrapeStatus.PARTIAL, ScrapeStatus.FAILED, ScrapeStatus.BLOCKED}
)


class ScrapeRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        site: SiteKey,
        category: Category,
        trigger: ScrapeTrigger,
        *,
        status: ScrapeStatus = ScrapeStatus.RUNNING,
        now: datetime | None = None,
    ) -> ScrapeRun:
        run = ScrapeRun(
            site=site,
            category=category,
            trigger=trigger,
            status=status,
            started_at=now or utc_now(),
        )
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: int) -> ScrapeRun | None:
        return self._session.get(ScrapeRun, run_id) if fits_int4(run_id) else None

    def update_counters(
        self,
        run: ScrapeRun,
        *,
        pages_fetched: int | None = None,
        items_parsed: int | None = None,
        items_failed: int | None = None,
        offers_upserted: int | None = None,
        price_changes: int | None = None,
    ) -> ScrapeRun:
        """Đặt (không cộng dồn) các bộ đếm được truyền; bộ đếm không truyền giữ nguyên."""
        updates = {
            "pages_fetched": pages_fetched,
            "items_parsed": items_parsed,
            "items_failed": items_failed,
            "offers_upserted": offers_upserted,
            "price_changes": price_changes,
        }
        for name, value in updates.items():
            if value is not None:
                setattr(run, name, value)
        self._session.flush()
        return run

    def set_status(
        self,
        run: ScrapeRun,
        status: ScrapeStatus,
        *,
        error_message: str | None = None,
        challenge: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScrapeRun:
        """Đổi trạng thái; `finished_at` chỉ có ở trạng thái kết thúc (và bị xóa khi chạy lại).

        `error_message` và `challenge` được thay bằng giá trị truyền vào (None là xóa), vì mỗi lần
        đổi trạng thái mô tả tình trạng mới của lượt.
        """
        run.status = status
        run.error_message = error_message
        run.challenge = None if challenge is None else dict(challenge)
        run.finished_at = (now or utc_now()) if status in FINISHED_STATUSES else None
        self._session.flush()
        return run

    def latest(self, site: SiteKey, category: Category) -> ScrapeRun | None:
        statement = (
            select(ScrapeRun)
            .where(ScrapeRun.site == site, ScrapeRun.category == category)
            .order_by(col(ScrapeRun.started_at).desc(), col(ScrapeRun.id).desc())
        )
        return self._session.exec(statement).first()

    def latest_succeeded(self, site: SiteKey, category: Category) -> ScrapeRun | None:
        """Lượt `SUCCEEDED` gần nhất, để so số sản phẩm với lượt trước (docs/06 §7).

        Lượt `tracked_refresh` chỉ chạm vài offer nên không được tính làm mốc so sánh.
        """
        statement = (
            select(ScrapeRun)
            .where(
                ScrapeRun.site == site,
                ScrapeRun.category == category,
                ScrapeRun.status == ScrapeStatus.SUCCEEDED,
                ScrapeRun.trigger != ScrapeTrigger.tracked_refresh,
            )
            .order_by(col(ScrapeRun.started_at).desc(), col(ScrapeRun.id).desc())
        )
        return self._session.exec(statement).first()

    def list_recent(self, *, site: SiteKey | None = None, limit: int = 20) -> list[ScrapeRun]:
        statement = select(ScrapeRun)
        if site is not None:
            statement = statement.where(ScrapeRun.site == site)
        statement = statement.order_by(
            col(ScrapeRun.started_at).desc(), col(ScrapeRun.id).desc()
        ).limit(limit)
        return list(self._session.exec(statement))

    def list_filtered(
        self,
        *,
        site: SiteKey | None = None,
        category: Category | None = None,
        status: ScrapeStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[ScrapeRun], int]:
        """Các lượt khớp bộ lọc (mới nhất trước) cho một trang kết quả, kèm tổng số lượt khớp."""
        conditions: list[ColumnElement[bool]] = []
        if site is not None:
            conditions.append(col(ScrapeRun.site) == site)
        if category is not None:
            conditions.append(col(ScrapeRun.category) == category)
        if status is not None:
            conditions.append(col(ScrapeRun.status) == status)
        total = self._session.exec(select(func.count()).select_from(ScrapeRun).where(*conditions))
        page = (
            select(ScrapeRun)
            .where(*conditions)
            .order_by(col(ScrapeRun.started_at).desc(), col(ScrapeRun.id).desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.exec(page)), int(total.one())

    def latest_blocked_since(self, site: SiteKey, since: datetime) -> ScrapeRun | None:
        """Lượt `BLOCKED` mới nhất của trang bắt đầu từ `since` (UTC); dùng cho thời gian nghỉ."""
        statement = (
            select(ScrapeRun)
            .where(
                ScrapeRun.site == site,
                ScrapeRun.status == ScrapeStatus.BLOCKED,
                col(ScrapeRun.started_at) >= since,
            )
            .order_by(col(ScrapeRun.started_at).desc(), col(ScrapeRun.id).desc())
        )
        return self._session.exec(statement).first()
