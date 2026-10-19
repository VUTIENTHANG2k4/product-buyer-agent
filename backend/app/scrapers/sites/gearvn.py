"""Scraper của GearVN (docs/06 §6, docs/sources/gearvn.md).

Bản khung của T3.1: chỉ đăng ký cấu hình để `fetch_page.py` và Fetcher lấy được độ trễ của trang
khi khảo sát. `enabled=False` nên `get_scraper` từ chối; T3.2 cài parser và bật trang.
"""

from typing import ClassVar

from app.domain.dto import ListingPage
from app.domain.enums import Category, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig


class GearVNScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.gearvn,
        base_url="https://gearvn.com",
        min_delay_s=5.0,
        supports_live_search=True,
        enabled=False,
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        raise NotImplementedError("GearVN parser is implemented in T3.2")
