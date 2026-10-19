"""M3b/T3.4: robots.txt bị chặn → lượt `BLOCKED` kèm thời gian nghỉ 24 giờ (docs/06 §3–§4).

Fetcher thật nói chuyện với một trang giả qua `httpx.MockTransport`, nên chạy đủ đường
robots.txt → `RobotsBlocked` → pipeline → `SiteCooldown`. Không có mạng thật.
"""

from collections.abc import Callable
from datetime import timedelta

import httpx
import pytest
from sqlmodel import Session

from app.config import Settings
from app.domain.enums import Category, ChallengeKind, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import SiteCooldown
from app.scrapers.http.errors import RobotsBlocked
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.pipeline import BLOCK_COOLDOWN
from tests.integration.test_pipeline import (
    BASE,
    LAPTOP,
    NOW,
    Clock,
    FakeTime,
    ScriptedFetcher,
    active_offers,
    card,
    clock,  # noqa: F401 - fixture
    factory,  # noqa: F401 - fixture
    listing,
    page,
    pipeline,
    real_site,  # noqa: F401 - fixture
    run_row,
)

ROBOTS_BLOCKS = [
    pytest.param(403, {}, "Forbidden", ChallengeKind.http_403, id="403"),
    pytest.param(429, {"Retry-After": "900"}, "Slow down", ChallengeKind.http_429, id="429"),
    pytest.param(
        503, {"cf-mitigated": "challenge"}, "challenge", ChallengeKind.http_403, id="503-cf"
    ),
    pytest.param(
        503,
        {"server": "cloudflare"},
        "<title>Just a moment...</title>",
        ChallengeKind.http_403,
        id="503-just-a-moment",
    ),
]


def blocked_site_fetcher(
    status: int, headers: dict[str, str], body: str, *, real: bool
) -> tuple[Fetcher, list[str]]:
    """Fetcher thật; mọi request tới robots.txt nhận phản hồi chặn, trang khác ghi lại để đếm."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(status, headers=headers, text=body)
        return httpx.Response(200, text="<html></html>")

    fake = FakeTime()
    settings = Settings(
        scraper_offline_only=not real,
        scraper_min_delay_seconds=0,
        mock_shop_url=BASE,
        mock_shop_delay_seconds=0,
    )
    transport = httpx.MockTransport(handler)
    fetcher = Fetcher(
        settings,
        transport=transport if real else None,
        mock_transport=None if real else transport,
        clock=fake.clock,
        sleep=fake.sleep,
        jitter=lambda: 0.0,
    )
    return fetcher, requested


@pytest.mark.parametrize(("status", "headers", "body", "kind"), ROBOTS_BLOCKS)
async def test_a_real_site_whose_robots_txt_is_blocked_ends_blocked_and_rests_24_hours(
    db_session: Session,
    factory: Callable[[], Session],  # noqa: F811
    clock: Clock,  # noqa: F811
    real_site: None,  # noqa: F811
    status: int,
    headers: dict[str, str],
    body: str,
    kind: ChallengeKind,
) -> None:
    fetcher, requested = blocked_site_fetcher(status, headers, body, real=True)
    pipe = pipeline(factory, fetcher, clock)

    blocked = await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)

    assert blocked.status is ScrapeStatus.BLOCKED
    assert blocked.challenge is not None
    assert blocked.challenge.kind is kind
    assert str(blocked.challenge.url) == "https://shop.example/robots.txt"
    assert (blocked.pages_fetched, blocked.offers_upserted) == (0, 0)
    run = run_row(db_session, blocked)
    assert run.status is ScrapeStatus.BLOCKED and run.finished_at == NOW
    assert requested == ["/robots.txt"]  # không có request nào tới trang danh sách

    clock.now = NOW + timedelta(hours=1)
    with pytest.raises(SiteCooldown) as error:
        await pipe.run(SiteKey.gearvn, Category.mouse, ScrapeTrigger.test)
    assert error.value.details["retry_after"] == NOW + BLOCK_COOLDOWN
    assert requested == ["/robots.txt"]  # trong lúc nghỉ cũng không chạm tới trang

    clock.now = NOW + BLOCK_COOLDOWN
    again = await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)
    assert again.status is ScrapeStatus.BLOCKED


async def test_an_ordinary_5xx_robots_txt_fails_the_run_without_a_cooldown(
    db_session: Session,
    factory: Callable[[], Session],  # noqa: F811
    clock: Clock,  # noqa: F811
    real_site: None,  # noqa: F811
) -> None:
    fetcher, _ = blocked_site_fetcher(500, {}, "Internal Server Error", real=True)
    pipe = pipeline(factory, fetcher, clock)

    first = await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)
    second = await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)

    assert (first.status, second.status) == (ScrapeStatus.FAILED, ScrapeStatus.FAILED)


@pytest.mark.parametrize(
    ("status", "headers", "body"),
    [
        pytest.param(403, {}, "Forbidden", id="403"),
        pytest.param(503, {"cf-mitigated": "challenge"}, "captcha", id="503-captcha-text"),
    ],
)
async def test_the_mock_shop_with_a_blocked_robots_txt_is_blocked_never_waiting_for_a_human(
    db_session: Session,
    factory: Callable[[], Session],  # noqa: F811
    clock: Clock,  # noqa: F811
    status: int,
    headers: dict[str, str],
    body: str,
) -> None:
    fetcher, requested = blocked_site_fetcher(status, headers, body, real=False)
    pipe = pipeline(factory, fetcher, clock)

    first = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    second = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert (first.status, second.status) == (ScrapeStatus.BLOCKED, ScrapeStatus.BLOCKED)
    assert first.challenge is not None and first.challenge.kind is not ChallengeKind.captcha
    assert requested == ["/robots.txt", "/robots.txt"]


async def test_robots_blocked_while_fetching_a_detail_page_stops_the_run_before_saving(
    db_session: Session,
    factory: Callable[[], Session],  # noqa: F811
    clock: Clock,  # noqa: F811
) -> None:
    """robots.txt hết hạn giữa lượt rồi bị chặn: không được nuốt như lỗi tải chi tiết thường."""
    detail = f"{BASE}/p/a"
    fetcher = ScriptedFetcher(
        {
            LAPTOP: page(listing([card("a", "Laptop Acer Mock A")])),
            detail: RobotsBlocked(
                "robots.txt blocked (HTTP 403)", url=f"{BASE}/robots.txt", status=403
            ),
        }
    )

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.BLOCKED
    assert result.challenge is not None and result.challenge.kind is ChallengeKind.http_403
    assert (result.pages_fetched, result.offers_upserted) == (0, 0)
    assert active_offers(db_session) == []
    assert fetcher.requested == [LAPTOP, detail]
