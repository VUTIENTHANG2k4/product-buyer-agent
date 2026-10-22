"""DTO quản trị thu thập: nguồn, lượt chạy, challenge cần người (docs/07 §3.6).

Không có `token` của challenge: đó là thông tin nội bộ để gửi đáp án, không đưa ra API.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.enums import Category, ChallengeKind, ScrapeStatus, ScrapeTrigger, SiteKey


class ScrapeRunView(BaseModel):
    """Một lượt thu thập: trạng thái, thống kê và lỗi (nếu có)."""

    run_id: int
    site: SiteKey
    category: Category
    status: ScrapeStatus
    trigger: ScrapeTrigger
    pages_fetched: int
    items_parsed: int
    items_failed: int
    offers_upserted: int
    price_changes: int
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None
    challenge_kind: ChallengeKind | None  # có khi lượt gặp challenge


class ChallengeView(BaseModel):
    """Challenge đang chờ người nhập đáp án (chỉ mock-shop)."""

    kind: ChallengeKind
    prompt: str | None
    image_url: str | None


class SourceView(BaseModel):
    """Một trang nguồn: cấu hình, tình trạng robots.txt và lượt chạy gần nhất."""

    key: SiteKey
    enabled: bool
    is_mock: bool
    categories: list[Category]
    # `unknown`: chưa tải robots.txt trong tiến trình này; `partial`: có luật chặn một phần.
    robots_status: Literal["allowed", "partial", "unknown"]
    effective_delay_s: float  # giây giữa hai request tới trang
    supports_live_search: bool
    last_run: ScrapeRunView | None
    cooldown_until: datetime | None  # chỉ có khi trang thật đang nghỉ sau BLOCKED


class ScrapeRunStarted(BaseModel):
    """POST /admin/scrape-runs → 202."""

    run_id: int


class ChallengeAnswered(BaseModel):
    """POST /admin/scrape-runs/{id}/challenge: đáp án đúng, lượt chạy tiếp ở nền."""

    status: Literal["RUNNING"]
