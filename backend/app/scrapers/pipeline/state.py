"""Hằng số, kết quả và trạng thái nội bộ của một lượt thu thập (docs/06 §7)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session

from app.db.models import Offer, ScrapeRun
from app.db.repositories import ScrapeRunRepository
from app.domain.dto import Challenge
from app.domain.enums import Category, ScrapeStatus, SiteKey
from app.domain.errors import RunNotFound
from app.scrapers.base import BaseScraper

BLOCK_COOLDOWN = timedelta(hours=24)  # nghỉ sau khi trang thật chặn (docs/02 §3)
# RUNNING quá lâu = tiến trình đã chết, không chặn lượt mới
RUNNING_STALE_AFTER = timedelta(hours=2)
NEEDS_HUMAN_STALE_AFTER = timedelta(hours=1)  # bỏ cuộc nếu không ai nhập đáp án
CANCELLED_BY_USER = "Đã hủy bởi người dùng."
FAILED_RATIO_LIMIT = 0.2  # items_failed / items_parsed > 20% → PARTIAL
DROP_RATIO_LIMIT = 0.5  # số sản phẩm giảm > 50% so với lượt trước → cảnh báo
DEFAULT_MAX_DETAIL_REQUESTS = 20  # giới hạn số trang chi tiết tải thêm mỗi lượt
MAX_CONSECUTIVE_REFRESH_FAILURES = 3  # lỗi tải liên tiếp khi làm mới giá thì dừng lượt
GONE_STATUSES = (404, 410)  # sản phẩm đã gỡ: không phải dấu hiệu trang đang hỏng
ACTIVE_STATUSES = (ScrapeStatus.PENDING, ScrapeStatus.RUNNING, ScrapeStatus.NEEDS_HUMAN)

SessionFactory = Callable[[], Session]


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
class Progress:
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
    loop: bool = False  # trang sau trỏ về URL đã tải (vòng lặp phân trang)
    detail_requests: int = 0


@dataclass(frozen=True)
class Verdict:
    status: ScrapeStatus
    message: str | None
    deactivate: bool = False


@dataclass(frozen=True)
class RunContext:
    run_id: int
    site: SiteKey
    category: Category
    started_at: datetime
    expect_items: bool
    previous_items: int | None  # items_parsed của lượt SUCCEEDED gần nhất
    # Lượt chỉ làm mới giá vài offer (`refresh_offers`): không bao giờ tắt offer "không còn thấy".
    partial_scope: bool = False


@dataclass
class Lifecycle:
    """Lượt đã được `execute` (hoặc `abandon`) chưa: mỗi lượt chỉ chạy một lần (T7.6)."""

    claimed: bool = False


@dataclass(frozen=True)
class StartedRun:
    """Lượt đã tạo (RUNNING) và chờ `ScrapePipeline.execute`. Chỉ `run_id`, `site`, `category` là
    thông tin công khai; phần còn lại là trạng thái nội bộ của pipeline."""

    scraper: BaseScraper = field(repr=False)
    context: RunContext = field(repr=False)
    progress: Progress = field(repr=False)
    start_page: int
    max_pages: int
    lifecycle: Lifecycle = field(default_factory=Lifecycle, repr=False)

    @property
    def run_id(self) -> int:
        return self.context.run_id

    @property
    def site(self) -> SiteKey:
        return self.context.site

    @property
    def category(self) -> Category:
        return self.context.category


def require_run_id(run: ScrapeRun) -> int:
    if run.id is None:  # pragma: no cover - flush luôn gán id
        raise RuntimeError("scrape run has no id after flush")
    return run.id


def require_offer_id(offer: Offer) -> int:
    if offer.id is None:  # pragma: no cover - upsert luôn trả offer đã lưu
        raise RuntimeError("offer has no id after upsert")
    return offer.id


def require_run(runs: ScrapeRunRepository, run_id: int) -> ScrapeRun:
    run = runs.get(run_id)
    if run is None:
        raise RunNotFound(details={"run_id": run_id})
    return run
