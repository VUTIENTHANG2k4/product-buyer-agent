"""Fetcher: cổng duy nhất để tải trang (docs/06 §3, quy tắc thu thập ở docs/02 §3).

Thứ tự mỗi request: chế độ ngoại tuyến → robots.txt → độ trễ theo domain → gửi → retry/chuyển hướng.
Scraper chỉ biết `PageFetcher`; không ai khác được tạo `httpx.AsyncClient` để tải trang.
"""

import asyncio
import logging
import math
import random
import ssl
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from http.cookiejar import DefaultCookiePolicy
from pathlib import Path
from types import TracebackType
from urllib.parse import urldefrag, urljoin, urlsplit

import certifi
import httpx

from app.config import Settings
from app.normalize.url import host_key
from app.scrapers.challenge import is_blocking_error_response
from app.scrapers.http.errors import (
    FetchFailed,
    FormNotAllowed,
    HttpStatusError,
    OfflineModeError,
    RedirectError,
    ResponseTooLarge,
    RobotsBlocked,
    RobotsDisallowed,
    RobotsUnavailable,
)
from app.scrapers.http.rate_limiter import DomainRateLimiter
from app.scrapers.http.raw_cache import RawCache
from app.scrapers.http.robots import RobotsCache, RobotsSnapshot
from app.scrapers.http.types import FetchResponse

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 5
RATE_LIMIT_MIN_WAIT_S = 60.0  # docs/06 §3: chờ 429 tối thiểu 60 giây
RATE_LIMIT_MAX_WAIT_S = 600.0  # Retry-After lớn hơn thì không chờ, coi là bị chặn
BACKOFF_BASE_S = 5.0  # chờ 5 · 2^n giây trước lần retry thứ n (n = 0, 1, …)
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # thân phản hồi lớn hơn (sau giải nén) bị từ chối
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
# Thân đã đọc xong và giải nén, nên bỏ các header mô tả thân gốc khi dựng lại phản hồi.
_BODY_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    """Nạp gói chứng chỉ một lần mỗi tiến trình (mỗi `httpx.AsyncClient` mới tốn ~0,3 giây)."""
    return ssl.create_default_context(cafile=certifi.where())


def _netloc(url: str) -> str:
    """`host[:port]` chuẩn hóa (chữ thường, bỏ cổng mặc định, IDN → punycode): khóa domain."""
    return host_key(url)


def _origin(url: str) -> str:
    return f"{urlsplit(url).scheme.lower()}://{host_key(url)}"


async def _get_bounded(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET đọc thân theo luồng; vượt `MAX_RESPONSE_BYTES` (sau giải nén) thì `ResponseTooLarge`.

    Kiểm `Content-Length` trước để khỏi tải thân khổng lồ, rồi cộng dồn từng đoạn vì header có thể
    dối hoặc vắng (chunked). Trả `httpx.Response` mới chứa thân đã đọc.
    """
    async with client.stream("GET", url) as response:
        declared = response.headers.get("content-length", "")
        if declared.isascii() and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge(f"Content-Length {declared} exceeds the limit", url=url)
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge(
                    f"response body exceeds {MAX_RESPONSE_BYTES // (1024 * 1024)} MB", url=url
                )
            chunks.append(chunk)
        headers = [
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() not in _BODY_HEADERS
        ]
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=b"".join(chunks),
            request=response.request,
        )


class Fetcher:
    """Tải trang qua robots.txt + độ trễ theo domain, thỏa `PageFetcher`.

    `site_delays` ánh xạ `netloc` → `SiteConfig.min_delay_s` của trang đó. Độ trễ của trang thật
    là `max(SCRAPER_MIN_DELAY_SECONDS, Crawl-delay, min_delay_s)` cộng nhiễu 0–1 giây; của
    mock-shop là `MOCK_SHOP_DELAY_SECONDS`, không nhiễu. `clock`, `sleep`, `wall_now` và `jitter`
    tiêm được để test không phải ngủ thật. Mock-shop có cookie phiên riêng (sau khi giải
    challenge); trang thật không bao giờ lưu cookie.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        site_delays: Mapping[str, float] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        mock_transport: httpx.AsyncBaseTransport | None = None,
        raw_cache_dir: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        jitter: Callable[[], float] = lambda: random.uniform(0.0, 1.0),
        backoff_base_s: float = BACKOFF_BASE_S,
    ) -> None:
        self._settings = settings
        self._user_agent = settings.scraper_user_agent
        self._site_delays = {host.lower(): delay for host, delay in (site_delays or {}).items()}
        self._mock_host = _netloc(settings.mock_shop_url)
        self._clock = clock
        self._sleep = sleep
        self._wall_now = wall_now
        self._jitter = jitter
        self._backoff_base_s = backoff_base_s
        self._limiter = DomainRateLimiter(clock=clock, sleep=sleep)
        self._robots = RobotsCache(self._load_robots, self._user_agent, clock=clock)
        self._raw_cache = RawCache(raw_cache_dir) if raw_cache_dir is not None else None
        headers = {"User-Agent": self._user_agent, "Accept-Language": "vi-VN,vi;q=0.9"}
        timeout = httpx.Timeout(settings.scraper_timeout_seconds)
        # Không theo chuyển hướng tự động (kiểm tra từng bước), không dùng proxy từ môi trường.
        self._web = httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            verify=_ssl_context(),
            transport=transport,
        )
        self._web.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))  # chặn mọi cookie
        self._mock = httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            verify=_ssl_context(),
            transport=mock_transport if mock_transport is not None else transport,
        )

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._web.aclose()
        await self._mock.aclose()

    # ---- API ----
    def robots_snapshot(self, url: str) -> RobotsSnapshot | None:
        """Tóm tắt robots.txt đã tải của domain chứa `url` (None nếu chưa tải); không gọi mạng."""
        return self._robots.snapshot(_origin(url))

    async def get(self, url: str) -> FetchResponse:
        """Tải `url`, theo chuyển hướng trong cùng domain tối đa 5 lần.

        Trả `FetchResponse` cho 2xx và cả 403/429 (sau khi đã chờ/thử lại theo §3) để scraper gọi
        `detect_challenge`. Ném `FetchError` cho robots chặn, chế độ ngoại tuyến, chuyển hướng ra
        ngoài domain, mã 4xx/5xx khác và khi hết lượt retry.
        """
        self._require_http(url)
        home = _netloc(url)
        current = url
        started = self._clock()
        for _ in range(MAX_REDIRECTS + 1):
            crawl_delay = await self._check_allowed(current)
            response = await self._send_with_retries(current, crawl_delay)
            if response.status_code in _REDIRECTS:
                current = self._redirect_target(response, current, home)
                continue
            return await self._finish(url, current, response, started)
        raise RedirectError(f"more than {MAX_REDIRECTS} redirects", url=url)

    async def post_form(self, url: str, data: Mapping[str, str]) -> FetchResponse:
        """Gửi form tới mock-shop (đáp án captcha); cookie phiên được giữ cho các `get` sau.

        Chỉ mock-shop nhận form: trang thật ném `FormNotAllowed`, không có request nào được gửi.
        Không retry và không theo chuyển hướng (một lần gửi = một đáp án); trả mọi mã trạng thái.
        """
        self._require_http(url)
        if not self._is_mock(url):
            raise FormNotAllowed("only the mock-shop accepts challenge answers", url=url)
        started = self._clock()
        crawl_delay = await self._check_allowed(url)
        await self._pace(url, crawl_delay)
        try:
            response = await self._mock.post(url, data=dict(data))
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            raise FetchFailed(f"{type(exc).__name__}: {exc}", url=url) from exc
        return FetchResponse(
            url=url,
            final_url=url,
            status=response.status_code,
            text=response.text,
            headers=dict(response.headers),
            elapsed_ms=max(0, int((self._clock() - started) * 1000)),
        )

    # ---- kiểm tra trước khi gửi ----
    @staticmethod
    def _require_http(url: str) -> None:
        try:
            parts = urlsplit(url)
            host_key(url)  # http/https tuyệt đối, cổng hợp lệ, host hợp lệ
        except ValueError as exc:
            raise RedirectError(f"not an absolute http(s) URL: {url[:80]!r}", url=url) from exc
        if parts.username is not None or parts.password is not None:
            # Không đăng nhập (docs/02 §3): userinfo sẽ thành header Authorization.
            raise RedirectError("URLs with credentials are not allowed", url=url)

    def _is_mock(self, url: str) -> bool:
        return _netloc(url) == self._mock_host

    def _check_offline(self, url: str) -> None:
        if self._settings.scraper_offline_only and not self._is_mock(url):
            raise OfflineModeError(
                f"SCRAPER_OFFLINE_ONLY=true blocks {_netloc(url)} (only the mock-shop is allowed)",
                url=url,
            )

    async def _check_allowed(self, url: str) -> float | None:
        """Ngoại tuyến + robots.txt. Trả `Crawl-delay` (giây) của domain nếu có."""
        self._check_offline(url)
        rules = await self._robots.rules(_origin(url))
        if not rules.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}", url=url)
        return rules.crawl_delay

    def _redirect_target(self, response: httpx.Response, current: str, home: str) -> str:
        location = response.headers.get("location")
        if not location:
            raise HttpStatusError(
                f"HTTP {response.status_code} without Location",
                url=current,
                status=response.status_code,
            )
        target = str(urldefrag(urljoin(current, str(location))).url)
        self._require_http(target)
        if _netloc(target) != home:
            raise RedirectError(f"redirect leaves {home}: {target[:120]}", url=current)
        return target

    # ---- độ trễ ----
    def _delay(self, url: str, crawl_delay: float | None) -> float:
        if self._is_mock(url):
            return self._settings.mock_shop_delay_seconds
        base = max(
            self._settings.scraper_min_delay_seconds,
            crawl_delay or 0.0,
            self._site_delays.get(_netloc(url), 0.0),
        )
        return base + self._jitter()

    async def _pace(self, url: str, crawl_delay: float | None) -> None:
        await self._limiter.wait(_netloc(url), self._delay(url, crawl_delay))

    # ---- gửi + retry ----
    def _client(self, url: str) -> httpx.AsyncClient:
        return self._mock if self._is_mock(url) else self._web

    async def _send_with_retries(self, url: str, crawl_delay: float | None) -> httpx.Response:
        retries = 0
        rate_limited = False
        while True:
            await self._pace(url, crawl_delay)
            failure: str
            retry_after: float | None = None
            try:
                response = await _get_bounded(self._client(url), url)
            except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
                # URL của ta đã được kiểm tra, nên chỉ có thể do `Location` hỏng/lạ (javascript:,
                # mailto:...): httpx dựng yêu cầu chuyển hướng ngay trong .get(). Không retry.
                raise RedirectError(
                    f"invalid redirect target ({type(exc).__name__})", url=url
                ) from exc
            except httpx.RequestError as exc:
                failure = f"{type(exc).__name__}: {exc}"
            else:
                status = response.status_code
                if status == 429:
                    wait = self._rate_limit_wait(response)
                    if rate_limited or wait is None:
                        return response  # kết quả cuối: scraper sẽ báo challenge http_429
                    rate_limited = True
                    logger.warning("HTTP 429 từ %s, chờ %.0f giây", _netloc(url), wait)
                    await self._sleep(wait)
                    continue
                if status < 400 or status == 403:
                    return response  # 403: không retry, scraper báo challenge http_403
                if is_blocking_error_response(status, response.headers, response.text):
                    logger.warning(
                        "HTTP %d của trang challenge từ %s, không thử lại", status, _netloc(url)
                    )
                    return response  # 5xx của CDN (Cloudflare…): scraper báo challenge, không retry
                if status < 500:
                    raise HttpStatusError(f"HTTP {status}", url=url, status=status)
                failure = f"HTTP {status}"
                if status == 503:
                    retry_after = self._retry_after_seconds(response)
            if retries >= self._settings.scraper_max_retries:
                raise FetchFailed(f"{failure} after {retries} retries", url=url)
            backoff = self._backoff_base_s * (2**retries)
            if retry_after is not None:
                if retry_after > RATE_LIMIT_MAX_WAIT_S:
                    # Máy chủ xin chờ quá lâu: không đợi, lượt dừng ở lỗi này (như 429 quá lớn).
                    raise FetchFailed(
                        f"{failure}, Retry-After {retry_after:.0f} s is too long", url=url
                    )
                backoff = max(backoff, retry_after)
            retries += 1
            logger.warning("Lỗi tải %s (%s), thử lại sau %.0f giây", _netloc(url), failure, backoff)
            await self._sleep(backoff)

    def _retry_after_seconds(self, response: httpx.Response) -> float:
        """Giây trong `Retry-After` (số giây hoặc ngày giờ HTTP); thiếu, hỏng, âm hoặc `nan` → 0."""
        value = str(response.headers.get("retry-after", "")).strip()
        seconds = 0.0
        if value:
            try:
                seconds = float(value)
            except ValueError:
                try:
                    seconds = (parsedate_to_datetime(value) - self._wall_now()).total_seconds()
                except (TypeError, ValueError):
                    seconds = 0.0
        if math.isnan(seconds):  # "nan" coi như thiếu header; "inf" rơi xuống nhánh quá lớn
            return 0.0
        return max(seconds, 0.0)

    def _rate_limit_wait(self, response: httpx.Response) -> float | None:
        """Giây cần chờ sau 429 (tối thiểu 60); `None` nếu `Retry-After` quá lớn để chờ."""
        seconds = self._retry_after_seconds(response)
        if seconds > RATE_LIMIT_MAX_WAIT_S:
            return None
        return max(seconds, RATE_LIMIT_MIN_WAIT_S)

    # ---- robots.txt ----
    async def _load_robots(self, origin: str) -> tuple[int, str]:
        """Tải robots.txt (cũng qua độ trễ theo domain). Lỗi mạng → `RobotsUnavailable`."""
        url = f"{origin}/robots.txt"
        for _ in range(3):
            await self._pace(url, None)
            try:
                response = await _get_bounded(self._client(url), url)
            except ResponseTooLarge as exc:
                raise RobotsUnavailable("robots.txt is too large to read", url=url) from exc
            except (httpx.RequestError, httpx.InvalidURL) as exc:
                raise RobotsUnavailable(
                    f"cannot fetch robots.txt ({type(exc).__name__})", url=url
                ) from exc
            if response.status_code in _REDIRECTS:
                location = response.headers.get("location")
                target = urldefrag(urljoin(url, location)).url if location else ""
                if target and _netloc(target) == _netloc(url):
                    url = target
                    continue
                raise RobotsUnavailable("robots.txt redirects outside the domain", url=url)
            status = response.status_code
            if status in (403, 429) or is_blocking_error_response(
                status, response.headers, response.text
            ):
                # Không lưu vào cache: lượt thu thập dừng `BLOCKED` và nghỉ 24 giờ (docs/06 §4).
                raise RobotsBlocked(f"robots.txt blocked (HTTP {status})", url=url, status=status)
            return status, response.text
        raise RobotsUnavailable("robots.txt redirects too many times", url=url)

    # ---- kết quả ----
    async def _finish(
        self, requested: str, final_url: str, response: httpx.Response, started: float
    ) -> FetchResponse:
        text = response.text
        if self._raw_cache is not None:
            try:
                await asyncio.to_thread(
                    self._raw_cache.save, _netloc(final_url), final_url, text, now=self._wall_now()
                )
            except OSError:
                logger.warning("Không ghi được raw cache cho %s", _netloc(final_url), exc_info=True)
        return FetchResponse(
            url=requested,
            final_url=final_url,
            status=response.status_code,
            text=text,
            headers=dict(response.headers),
            elapsed_ms=max(0, int((self._clock() - started) * 1000)),
        )
