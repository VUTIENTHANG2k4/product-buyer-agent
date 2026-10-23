"""Tìm trực tiếp tầng 2 (docs/03 §5.3, ADR-0010): nhóm sản phẩm ngoài 4 nhóm lõi.

Tuần tự từng trang có `supports_live_search` (Fetcher giữ độ trễ ≥ 5 s/domain), tối đa
`MAX_PER_SITE` kết quả mỗi trang, cache theo (trang, từ khóa) `LIVE_SEARCH_CACHE_TTL_HOURS` giờ.
Lọc giá và cắt `limit_per_site` làm **sau** khi đọc cache, nên cache không phụ thuộc khoảng giá.
Trang chặn (captcha, 403, robots 403/429) được nghỉ 24 giờ như lượt thu thập. Không ghi
`Product`/`Offer`: kết quả là dữ liệu chưa chuẩn hóa.
"""

import asyncio
import logging
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final

from app.config import Settings
from app.db.models import utc_now
from app.db.repositories import LiveSearchCacheRepository, ScrapeRunRepository
from app.domain.enums import SiteKey
from app.domain.errors import ValidationFailed
from app.domain.live_search import LiveSearchItem, LiveSearchResult, SkippedSite
from app.normalize.url import clean_url
from app.scrapers.base import BaseScraper
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.errors import FetchError, OfflineModeError, RobotsBlocked, RobotsDisallowed
from app.scrapers.http.types import PageFetcher
from app.scrapers.pipeline import BLOCK_COOLDOWN
from app.scrapers.registry import SCRAPERS
from app.services.database import SessionFactory
from app.services.views import Clock, aware_now

logger = logging.getLogger(__name__)

MAX_PER_SITE: Final = 10  # số kết quả giữ trong cache mỗi (trang, từ khóa)
MAX_QUERY_CHARS: Final = 200
_KEY_PREFIX: Final = "live:v1"

REASON_OFFLINE: Final = "chế độ ngoại tuyến (SCRAPER_OFFLINE_ONLY=true), không truy cập trang thật"
REASON_BLOCKED: Final = "trang chặn truy cập, tạm nghỉ 24 giờ"
REASON_ROBOTS: Final = "robots.txt không cho phép tìm kiếm"
REASON_FAILED: Final = "không tải được trang tìm kiếm"


def normalize_query(query: str) -> str:
    """NFC, chữ thường, gộp khoảng trắng; ném `ValidationFailed` nếu rỗng hoặc quá dài."""
    text = " ".join(unicodedata.normalize("NFC", query).casefold().split())
    if not text:
        raise ValidationFailed("Từ khóa tìm kiếm không được để trống.")
    if len(text) > MAX_QUERY_CHARS:
        raise ValidationFailed(f"Từ khóa tìm kiếm tối đa {MAX_QUERY_CHARS} ký tự.")
    return text


def cache_key(site: SiteKey, normalized_query: str) -> str:
    return f"{_KEY_PREFIX}:{site.value}:{normalized_query}"


def blocked_key(site: SiteKey) -> str:
    return f"{_KEY_PREFIX}:blocked:{site.value}"


class LiveSearchService:
    def __init__(
        self,
        session_factory: SessionFactory,
        settings: Settings,
        fetcher: PageFetcher,
        clock: Clock = utc_now,
        scrapers: Mapping[SiteKey, type[BaseScraper]] = SCRAPERS,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._fetcher = fetcher
        self._clock = clock
        self._scrapers = scrapers
        self._lock = asyncio.Lock()  # một lượt tìm tại một thời điểm: tuần tự và tránh tìm trùng

    async def search(
        self,
        query: str,
        *,
        price_min: int | None = None,
        price_max: int | None = None,
        limit_per_site: int = 5,
    ) -> LiveSearchResult:
        """Tìm `query` ở các trang tầng 2; trang lỗi/chặn vào `sites_skipped`, không ném lỗi."""
        normalized = normalize_query(query)
        if limit_per_site < 1:
            raise ValidationFailed("limit_per_site phải >= 1.")
        if price_min is not None and price_max is not None and price_min > price_max:
            raise ValidationFailed("price_min không được lớn hơn price_max.")
        async with self._lock:
            now = aware_now(self._clock)
            searched: list[SiteKey] = []
            skipped: list[SkippedSite] = []
            items: list[LiveSearchItem] = []
            cache_hits: list[bool] = []
            for scraper_cls in self._candidates(skipped):
                site = scraper_cls.config.key
                found, from_cache, reason = await self._search_site(
                    scraper_cls, query.strip(), normalized, now
                )
                if reason is not None:
                    skipped.append(SkippedSite(site=site, reason=reason))
                    continue
                searched.append(site)
                cache_hits.append(from_cache)
                items.extend(_filter(found, price_min, price_max)[:limit_per_site])
        return LiveSearchResult(
            items=items,
            sites_searched=searched,
            sites_skipped=skipped,
            from_cache=bool(cache_hits) and all(cache_hits),
        )

    def _candidates(self, skipped: list[SkippedSite]) -> list[type[BaseScraper]]:
        """Trang tầng 2 được tìm: ngoại tuyến chỉ mock-shop (trang thật vào `skipped`), ngược lại
        chỉ trang thật. Trang tắt (`enabled=False`) bị bỏ qua."""
        offline = self._settings.scraper_offline_only
        chosen: list[type[BaseScraper]] = []
        for scraper_cls in self._scrapers.values():
            config = scraper_cls.config
            if not config.supports_live_search or not config.enabled:
                continue
            if config.is_mock == offline:
                chosen.append(scraper_cls)
            elif offline:  # trang thật khi đang ngoại tuyến: báo lý do thay vì ném OfflineModeError
                skipped.append(SkippedSite(site=config.key, reason=REASON_OFFLINE))
        return chosen

    async def _search_site(
        self, scraper_cls: type[BaseScraper], query: str, normalized: str, now: datetime
    ) -> tuple[list[LiveSearchItem], bool, str | None]:
        """(kết quả, lấy từ cache?, lý do bỏ qua). Có lý do thì kết quả rỗng."""
        site = scraper_cls.config.key
        if not scraper_cls.config.is_mock and await self._is_cooling_down(site, now):
            return [], False, REASON_BLOCKED
        cached = await self._read_cache(site, cache_key(site, normalized), now)
        if cached is not None:
            return cached, True, None
        scraper = scraper_cls(self._fetcher)
        try:
            found = await scraper.live_search(query, MAX_PER_SITE)
        except (ChallengeDetected, RobotsBlocked):
            logger.warning("Tìm trực tiếp: %s chặn truy cập, nghỉ %s", site, BLOCK_COOLDOWN)
            await self._write_cache(blocked_key(site), [{"reason": REASON_BLOCKED}], now)
            return [], False, REASON_BLOCKED
        except OfflineModeError:
            return [], False, REASON_OFFLINE
        except RobotsDisallowed:
            return [], False, REASON_ROBOTS
        except FetchError as error:
            logger.warning("Tìm trực tiếp: %s lỗi %s", site, type(error).__name__)
            return [], False, REASON_FAILED
        stored: list[dict[str, Any]] = []
        for listing in found:
            try:
                stored.append(
                    {
                        "title": listing.title,
                        "price": listing.price,
                        "url": clean_url(str(listing.url)),
                    }
                )
            except ValueError:  # URL không làm sạch được (quá dài, scheme lạ): bỏ mục này
                logger.warning("Tìm trực tiếp: bỏ mục có URL không hợp lệ ở %s", site)
        await self._write_cache(cache_key(site, normalized), stored, now)
        return [_item(site, entry, now) for entry in stored], False, None

    # ---- CSDL (repo đồng bộ → chạy trong thread, mỗi lần một session ngắn) ----
    async def _is_cooling_down(self, site: SiteKey, now: datetime) -> bool:
        def work() -> bool:
            with self._session_factory() as session:
                ttl = BLOCK_COOLDOWN
                marker = LiveSearchCacheRepository(session).get(
                    blocked_key(site), max_age=ttl, now=now
                )
                blocked = ScrapeRunRepository(session).latest_blocked_since(site, now - ttl)
                return marker is not None or blocked is not None

        return await asyncio.to_thread(work)

    async def _read_cache(
        self, site: SiteKey, key: str, now: datetime
    ) -> list[LiveSearchItem] | None:
        max_age = timedelta(hours=self._settings.live_search_cache_ttl_hours)

        def work() -> list[LiveSearchItem] | None:
            with self._session_factory() as session:
                entry = LiveSearchCacheRepository(session).get(key, max_age=max_age, now=now)
                if entry is None:
                    return None
                try:
                    return [_item(site, dict(raw), entry.created_at) for raw in entry.results]
                except (KeyError, TypeError, ValueError):  # mục hỏng: coi như chưa có cache
                    logger.warning("Tìm trực tiếp: bỏ mục cache hỏng %s", key)
                    return None

        return await asyncio.to_thread(work)

    async def _write_cache(self, key: str, results: list[dict[str, Any]], now: datetime) -> None:
        def work() -> None:
            with self._session_factory() as session:
                LiveSearchCacheRepository(session).put(key, results, now=now)
                session.commit()

        await asyncio.to_thread(work)


def _item(site: SiteKey, entry: dict[str, Any], scraped_at: datetime) -> LiveSearchItem:
    return LiveSearchItem(
        site=site,
        title=entry["title"],
        price=entry.get("price"),
        url=entry["url"],
        scraped_at=scraped_at,
    )


def _filter(
    items: list[LiveSearchItem], price_min: int | None, price_max: int | None
) -> list[LiveSearchItem]:
    """Lọc theo khoảng giá; có bất kỳ cận nào thì bỏ mục không có giá (không đoán)."""
    if price_min is None and price_max is None:
        return items
    kept: list[LiveSearchItem] = []
    for item in items:
        if item.price is None:
            continue
        if price_min is not None and item.price < price_min:
            continue
        if price_max is not None and item.price > price_max:
            continue
        kept.append(item)
    return kept
