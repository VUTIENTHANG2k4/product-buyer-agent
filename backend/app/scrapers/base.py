"""Lớp nền của mọi scraper (docs/06 §2).

`parse_*` là hàm thuần (không I/O) và được test bằng fixture HTML. Phần điều phối (`crawl_category`,
`fetch_detail`, `live_search`) chỉ gọi `PageFetcher`, nên robots.txt, độ trễ và chế độ ngoại tuyến
luôn do Fetcher xử lý.
"""

import math
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.domain.dto import Challenge, ListingItem, ListingPage, ProductDetail
from app.domain.enums import Category, SiteKey
from app.scrapers.challenge import ChallengeDetected, detect_challenge, soft_block_challenge
from app.scrapers.http.types import FetchResponse, PageFetcher


def _host(url: str) -> str:
    """Máy chủ (kèm cổng nếu có) của một URL http/https, chữ thường; ném `ValueError` nếu khác."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"not an absolute http(s) URL: {url!r}")
    return parts.netloc.lower()


@dataclass(frozen=True)
class SiteConfig:
    """Cấu hình tĩnh một trang. `min_delay_s` tính bằng giây."""

    key: SiteKey
    base_url: str
    min_delay_s: float  # độ trễ thật = max(env, robots, giá trị này); mock-shop dùng biến riêng
    requires_js: bool = False
    supports_live_search: bool = False  # tầng 2
    categories: Mapping[Category, str] = field(default_factory=dict)  # nhóm -> URL danh mục
    is_mock: bool = False
    enabled: bool = True  # tắt nguồn bị loại (T0.4) hoặc bị chặn lặp lại

    def __post_init__(self) -> None:
        if not math.isfinite(self.min_delay_s) or self.min_delay_s < 0:
            raise ValueError(f"min_delay_s must be finite and >= 0, got {self.min_delay_s!r}")
        base_host = _host(self.base_url)
        for category, url in self.categories.items():
            if _host(url) != base_host:
                raise ValueError(f"category {category} URL is outside {self.base_url}: {url}")
        object.__setattr__(self, "categories", MappingProxyType(dict(self.categories)))


class BaseScraper(ABC):
    """Giao diện scraper một trang; lớp con khai báo `config` và cài `parse_listing`."""

    config: ClassVar[SiteConfig]

    def __init__(self, fetcher: PageFetcher) -> None:
        if not isinstance(getattr(type(self), "config", None), SiteConfig):
            raise TypeError(f"{type(self).__name__} must define a SiteConfig in `config`")
        self._fetcher = fetcher

    # ---- URL ----
    def listing_url(self, category: Category, page: int) -> str:
        """URL trang danh sách thứ `page` (từ 1). Mặc định thêm `?page=N` từ trang 2."""
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        base = self.config.categories.get(category)
        if base is None:
            raise ValueError(f"{self.config.key} has no listing URL for category {category}")
        if page == 1:
            return base
        parts = urlsplit(base)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
        query.append(("page", str(page)))
        return urlunsplit(parts._replace(query=urlencode(query)))

    def search_url(self, query: str) -> str:
        """URL tìm kiếm; chỉ trang có `supports_live_search` cài đặt."""
        raise NotImplementedError

    # ---- parse (hàm thuần) ----
    @abstractmethod
    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage: ...

    def parse_detail(self, html: str, url: str) -> ProductDetail:
        raise NotImplementedError

    def parse_search(self, html: str, page_url: str) -> list[ListingItem]:
        return self.parse_listing(html, Category.other, page_url).items

    # ---- phát hiện challenge (mặc định dùng detector chung) ----
    def detect_challenge(self, resp: FetchResponse) -> Challenge | None:
        """Trang có thể ghi đè khi khảo sát thấy dấu hiệu riêng hoặc báo nhầm."""
        return detect_challenge(resp, self.config.key)

    def challenge_submission(self, challenge: Challenge, answer: str) -> tuple[str, dict[str, str]]:
        """(URL, dữ liệu form) để gửi đáp án; chỉ trang có luồng nhập đáp án (mock-shop) cài đặt."""
        raise NotImplementedError(f"{self.config.key} has no challenge answer form")

    # ---- điều phối ----
    async def crawl_category(
        self,
        category: Category,
        max_pages: int,
        *,
        start_page: int = 1,
        expect_items: bool = False,
    ) -> AsyncIterator[ListingPage]:
        """Lần lượt tải và parse các trang danh sách từ `start_page` đến trang số `max_pages`.

        `start_page` dùng để tiếp tục sau khi người dùng giải challenge (HITL). `expect_items=True`
        (lượt trước có sản phẩm) biến trang 1 rỗng thành `soft_block`. Ném `ChallengeDetected`
        khi gặp challenge; không bao giờ tự xử lý. Dừng nếu trang sau trỏ về URL đã tải. Là async
        generator nên `ValueError` về tham số chỉ phát ra ở lần lặp đầu tiên.
        """
        if max_pages < 1 or start_page < 1:
            raise ValueError("max_pages and start_page must be >= 1")
        base_host = _host(self.config.base_url)
        url = self.listing_url(category, start_page)
        visited = {url}
        for page_no in range(start_page, max_pages + 1):
            resp = await self._fetcher.get(url)
            self._raise_if_challenge(resp)
            page = self.parse_listing(resp.text, category, resp.final_url)
            if page_no == 1 and expect_items and not page.items:
                raise ChallengeDetected(soft_block_challenge(self.config.key, resp.final_url))
            yield page
            if not page.has_next:
                return
            next_url = str(page.next_url) if page.next_url is not None else None
            if next_url is not None and _host(next_url) == base_host:
                url = next_url
            else:
                url = self.listing_url(category, page_no + 1)
            if url in visited:
                return
            visited.add(url)

    async def fetch_detail(self, url: str) -> ProductDetail:
        """Tải và parse trang chi tiết; `url` phải thuộc domain của trang."""
        if _host(url) != _host(self.config.base_url):
            raise ValueError(f"{url} is outside {self.config.base_url}")
        resp = await self._fetcher.get(url)
        self._raise_if_challenge(resp)
        return self.parse_detail(resp.text, url)

    async def live_search(self, query: str, limit: int) -> list[ListingItem]:
        """Tìm trực tiếp (tầng 2); tối đa `limit` kết quả."""
        if not self.config.supports_live_search:
            raise NotImplementedError(f"{self.config.key} does not support live search")
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        resp = await self._fetcher.get(self.search_url(query))
        self._raise_if_challenge(resp)
        return self.parse_search(resp.text, resp.final_url)[:limit]

    def _raise_if_challenge(self, resp: FetchResponse) -> None:
        challenge = self.detect_challenge(resp)
        if challenge is not None:
            raise ChallengeDetected(challenge)
