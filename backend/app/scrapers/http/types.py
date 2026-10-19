"""Kiểu dữ liệu ranh giới giữa scraper và Fetcher (docs/06 §2–3).

`BaseScraper` chỉ biết `PageFetcher`; lớp `Fetcher` thật (robots, độ trễ, retry, T2.1) và
fetcher giả trong test cùng thỏa Protocol này.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class FetchResponse:
    """Một phản hồi đã tải. Thời gian tính bằng mili-giây."""

    url: str  # URL đã yêu cầu
    final_url: str  # URL cuối sau chuyển hướng
    status: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)
    elapsed_ms: int = 0
    from_cache: bool = False


class PageFetcher(Protocol):
    """Tải một trang qua robots.txt + độ trễ theo domain.

    Hợp đồng: trả `FetchResponse` kể cả khi `status` là 403/429 (sau retry) để scraper gọi
    `detect_challenge`; chỉ ném lỗi khi không được phép tải (robots, chế độ ngoại tuyến) hoặc hết
    lượt retry vì lỗi mạng/5xx.
    """

    async def get(self, url: str) -> FetchResponse: ...


class FormFetcher(PageFetcher, Protocol):
    """`PageFetcher` có thêm gửi form: chỉ để nhập đáp án captcha của mock-shop (HITL)."""

    async def post_form(self, url: str, data: Mapping[str, str]) -> FetchResponse: ...
