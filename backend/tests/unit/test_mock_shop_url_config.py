"""MOCK_SHOP_URL chỉ được trỏ vào máy cục bộ (mock-shop được miễn offline/robots/độ trễ thật)."""

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.config import Settings
from app.scrapers.http.errors import FetchFailed
from app.scrapers.http.fetcher import Fetcher


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8100", "http://127.0.0.1:9000", "https://localhost", "http://[::1]:8100"],
)
def test_local_mock_shop_urls_are_accepted(url: str) -> None:
    assert Settings(mock_shop_url=url).mock_shop_url == url


def test_trailing_slash_is_removed() -> None:
    assert Settings(mock_shop_url="http://localhost:8100/").mock_shop_url == "http://localhost:8100"


@pytest.mark.parametrize(
    "url",
    [
        "https://shop.example",
        "http://gearvn.com",
        "http://localhost.evil.example:8100",
        "http://user@evil.example/",
        "ftp://localhost",
        "localhost:8100",
        "",
        "http://10.0.0.5:8100",
    ],
)
def test_non_local_or_malformed_mock_shop_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(mock_shop_url=url)
    assert "mock_shop_url" in str(error.value)


@pytest.mark.parametrize(
    "error",
    [httpx.DecodingError("bad gzip"), httpx.UnsupportedProtocol("x"), httpx.InvalidURL("x")],
)
async def test_other_httpx_errors_become_fetch_failed_instead_of_escaping(
    error: Exception,
) -> None:
    settings = Settings(
        scraper_offline_only=False, scraper_min_delay_seconds=0, scraper_max_retries=0
    )

    async def no_sleep(_: float) -> None:
        return None

    with respx.mock(assert_all_called=False) as router:
        router.get("https://shop.example/robots.txt").respond(404)
        router.get("https://shop.example/p").mock(side_effect=error)
        fetcher = Fetcher(settings, sleep=no_sleep, jitter=lambda: 0.0)
        with pytest.raises(FetchFailed):
            await fetcher.get("https://shop.example/p")
        await fetcher.aclose()
