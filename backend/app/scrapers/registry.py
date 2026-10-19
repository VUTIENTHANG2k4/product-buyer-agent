"""Đăng ký scraper theo trang (docs/06 §2). Thêm trang mới = thêm một dòng vào `SCRAPERS`."""

from app.domain.enums import SiteKey
from app.scrapers.base import BaseScraper
from app.scrapers.http.types import PageFetcher

SCRAPERS: dict[SiteKey, type[BaseScraper]] = {}


class SiteNotAvailable(LookupError):
    """Trang chưa có scraper hoặc đã bị tắt (`SiteConfig.enabled=False`)."""


def get_scraper(site: SiteKey, fetcher: PageFetcher) -> BaseScraper:
    """Dựng scraper của `site`; ném `SiteNotAvailable` nếu chưa đăng ký hoặc đã tắt."""
    scraper_cls = SCRAPERS.get(site)
    if scraper_cls is None:
        raise SiteNotAvailable(f"no scraper registered for site {site}")
    if scraper_cls.config.key != site:
        raise SiteNotAvailable(f"scraper registered for {site} is configured for another site")
    if not scraper_cls.config.enabled:
        raise SiteNotAvailable(f"site {site} is disabled")
    return scraper_cls(fetcher)
