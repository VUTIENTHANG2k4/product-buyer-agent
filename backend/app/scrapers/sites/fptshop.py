"""Scraper của FPT Shop (docs/06 §6, docs/sources/fptshop.md).

Khung tạm của T4.1 để `scripts.fetch_page` lưu được fixture qua Fetcher; phần parse viết ở T4.2.
"""

from typing import ClassVar

from app.domain.dto import ListingPage
from app.domain.enums import Category, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig

_BASE_URL = "https://fptshop.com.vn"


class FptShopScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.fptshop,
        base_url=_BASE_URL,
        min_delay_s=5.0,
        categories={
            Category.laptop: f"{_BASE_URL}/may-tinh-xach-tay",
            Category.mouse: f"{_BASE_URL}/phu-kien/chuot",
            Category.keyboard: f"{_BASE_URL}/phu-kien/ban-phim",
            Category.headset: f"{_BASE_URL}/phu-kien/tai-nghe",
        },
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        raise NotImplementedError("FptShopScraper.parse_listing is written in T4.2")
