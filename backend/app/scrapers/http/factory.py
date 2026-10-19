"""Dựng `Fetcher` thật từ cấu hình và registry (độ trễ riêng của từng trang)."""

from pathlib import Path
from urllib.parse import urlsplit

from app.config import Settings, get_settings
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.registry import SCRAPERS

RAW_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"  # backend/data/raw (gitignore)


def site_delays() -> dict[str, float]:
    """`netloc` → `SiteConfig.min_delay_s` của mọi trang đã đăng ký."""
    return {
        urlsplit(scraper.config.base_url).netloc.lower(): scraper.config.min_delay_s
        for scraper in SCRAPERS.values()
    }


def build_fetcher(
    settings: Settings | None = None, *, raw_cache_dir: Path | None = RAW_CACHE_DIR
) -> Fetcher:
    """Fetcher dùng `SCRAPER_*`/`MOCK_SHOP_*` và độ trễ riêng của từng trang đã đăng ký."""
    return Fetcher(
        settings or get_settings(),
        site_delays=site_delays(),
        raw_cache_dir=raw_cache_dir,
    )
