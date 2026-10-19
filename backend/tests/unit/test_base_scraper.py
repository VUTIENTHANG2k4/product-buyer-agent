"""BaseScraper (app/scrapers/base.py) với fetcher giả: không gọi mạng."""

import json
from typing import ClassVar

import pytest

from app.domain.dto import Challenge, ListingItem, ListingPage, ProductDetail
from app.domain.enums import Category, ChallengeKind, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.types import FetchResponse
from tests.fakes import FakeFetcher

BASE = "https://shop.example"
LAPTOP = f"{BASE}/c/laptop"
PAGE2 = f"{LAPTOP}?page=2"
SEARCH = f"{BASE}/search?q=loa"


def response(
    n_items: int = 0,
    next_url: str | None = None,
    *,
    url: str = LAPTOP,
    status: int = 200,
    text: str | None = None,
) -> FetchResponse:
    if text is None:
        titles = [f"Mock Item {i}" for i in range(n_items)]
        text = json.dumps({"items": titles, "next": next_url})
    return FetchResponse(url=url, final_url=url, status=status, text=text)


class DummyScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.mockshop,
        base_url=BASE,
        min_delay_s=0.0,
        supports_live_search=True,
        categories={Category.laptop: LAPTOP, Category.mouse: f"{BASE}/c/mouse?sort=new&page=9"},
    )

    def search_url(self, query: str) -> str:
        return f"{BASE}/search?q={query}"

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        data = json.loads(html)
        items = [
            ListingItem.model_validate(
                {
                    "site": SiteKey.mockshop,
                    "url": f"{BASE}/p/{title.replace(' ', '-').lower()}",
                    "title": title,
                    "category_hint": category,
                }
            )
            for title in data["items"]
        ]
        return ListingPage.model_validate(
            {"items": items, "has_next": data["next"] is not None, "next_url": data["next"]}
        )

    def parse_detail(self, html: str, url: str) -> ProductDetail:
        return ProductDetail.model_validate({"url": url, "raw_specs": {"html": html}})


def make(pages: dict[str, FetchResponse] | None = None) -> tuple[DummyScraper, FakeFetcher]:
    fetcher = FakeFetcher(pages or {})
    return DummyScraper(fetcher), fetcher


async def crawl(
    scraper: BaseScraper, max_pages: int, *, start_page: int = 1, expect_items: bool = False
) -> list[ListingPage]:
    return [
        page
        async for page in scraper.crawl_category(
            Category.laptop, max_pages, start_page=start_page, expect_items=expect_items
        )
    ]


# --- khởi tạo -------------------------------------------------------------------------------


def test_scraper_without_config_cannot_be_instantiated() -> None:
    class Bare(BaseScraper):
        def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
            return ListingPage()

    with pytest.raises(TypeError, match="SiteConfig"):
        Bare(FakeFetcher({}))


def test_base_scraper_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        BaseScraper(FakeFetcher({}))  # type: ignore[abstract]


# --- URL ------------------------------------------------------------------------------------


def test_listing_url_page_one_is_the_category_url() -> None:
    assert make()[0].listing_url(Category.laptop, 1) == LAPTOP


def test_listing_url_adds_page_parameter_from_page_two() -> None:
    assert make()[0].listing_url(Category.laptop, 3) == f"{LAPTOP}?page=3"


def test_listing_url_keeps_existing_query_and_replaces_page() -> None:
    assert make()[0].listing_url(Category.mouse, 2) == f"{BASE}/c/mouse?sort=new&page=2"


@pytest.mark.parametrize("page", [0, -1])
def test_listing_url_rejects_page_below_one(page: int) -> None:
    with pytest.raises(ValueError, match="page"):
        make()[0].listing_url(Category.laptop, page)


def test_listing_url_rejects_unconfigured_category() -> None:
    with pytest.raises(ValueError, match="headset"):
        make()[0].listing_url(Category.headset, 1)


def test_search_and_detail_parsers_are_not_implemented_by_default() -> None:
    class ListOnly(BaseScraper):
        config: ClassVar[SiteConfig] = DummyScraper.config

        def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
            return ListingPage()

    scraper = ListOnly(FakeFetcher({}))
    with pytest.raises(NotImplementedError):
        scraper.search_url("loa")
    with pytest.raises(NotImplementedError):
        scraper.parse_detail("", LAPTOP)


# --- crawl_category -------------------------------------------------------------------------


async def test_crawl_stops_when_there_is_no_next_page() -> None:
    scraper, fetcher = make({LAPTOP: response(2, PAGE2), PAGE2: response(1, url=PAGE2)})
    pages = await crawl(scraper, max_pages=5)
    assert [len(p.items) for p in pages] == [2, 1]
    assert fetcher.requested == [LAPTOP, PAGE2]


async def test_crawl_stops_at_max_pages_even_if_more_exist() -> None:
    page3 = f"{LAPTOP}?page=3"
    scraper, fetcher = make({LAPTOP: response(1, PAGE2), PAGE2: response(1, page3, url=PAGE2)})
    assert len(await crawl(scraper, max_pages=2)) == 2
    assert fetcher.requested == [LAPTOP, PAGE2]


async def test_crawl_ignores_next_url_on_another_host() -> None:
    other = "https://other.example/c/laptop?page=2"
    scraper, fetcher = make({LAPTOP: response(1, other), PAGE2: response(1, url=PAGE2)})
    await crawl(scraper, max_pages=5)
    assert fetcher.requested == [LAPTOP, PAGE2]


async def test_crawl_follows_next_url_on_the_same_host() -> None:
    custom = f"{BASE}/c/laptop/trang-2"
    scraper, fetcher = make({LAPTOP: response(1, custom), custom: response(1, url=custom)})
    await crawl(scraper, max_pages=5)
    assert fetcher.requested == [LAPTOP, custom]


async def test_crawl_can_resume_from_a_later_page() -> None:
    page3 = f"{LAPTOP}?page=3"
    scraper, fetcher = make({page3: response(2, url=page3)})
    pages = await crawl(scraper, max_pages=5, start_page=3)
    assert len(pages) == 1
    assert fetcher.requested == [page3]


async def test_crawl_resuming_beyond_max_pages_yields_nothing() -> None:
    scraper, fetcher = make()
    assert await crawl(scraper, max_pages=2, start_page=3) == []
    assert fetcher.requested == []


@pytest.mark.parametrize(("max_pages", "start_page"), [(0, 1), (-1, 1), (3, 0)])
async def test_crawl_rejects_invalid_page_bounds(max_pages: int, start_page: int) -> None:
    with pytest.raises(ValueError, match=">= 1"):
        await crawl(make()[0], max_pages=max_pages, start_page=start_page)


@pytest.mark.parametrize(
    ("status", "kind"),
    [(403, ChallengeKind.http_403), (429, ChallengeKind.http_429)],
)
async def test_crawl_raises_challenge_detected_on_blocking_status(
    status: int, kind: ChallengeKind
) -> None:
    scraper, _ = make({LAPTOP: response(status=status, text="")})
    with pytest.raises(ChallengeDetected) as info:
        await crawl(scraper, max_pages=3)
    assert info.value.challenge.kind is kind
    assert info.value.challenge.site is SiteKey.mockshop


async def test_crawl_raises_on_captcha_page_after_yielding_earlier_pages() -> None:
    captcha = response(url=PAGE2, text='<div id="captcha">AB3XZ</div>')
    scraper, _ = make({LAPTOP: response(1, PAGE2), PAGE2: captcha})
    seen: list[ListingPage] = []
    with pytest.raises(ChallengeDetected) as info:
        async for page in scraper.crawl_category(Category.laptop, 5):
            seen.append(page)
    assert len(seen) == 1
    assert info.value.challenge.kind is ChallengeKind.captcha


async def test_empty_first_page_is_soft_block_only_when_items_were_expected() -> None:
    scraper, _ = make({LAPTOP: response(0)})
    assert [len(p.items) for p in await crawl(scraper, max_pages=3)] == [0]
    with pytest.raises(ChallengeDetected) as info:
        await crawl(scraper, max_pages=3, expect_items=True)
    assert info.value.challenge.kind is ChallengeKind.soft_block


async def test_expect_items_flags_neither_full_first_page_nor_empty_later_page() -> None:
    scraper, _ = make({LAPTOP: response(1, PAGE2), PAGE2: response(0, url=PAGE2)})
    pages = await crawl(scraper, max_pages=3, expect_items=True)
    assert [len(p.items) for p in pages] == [1, 0]


async def test_subclass_can_override_challenge_detection() -> None:
    class Lenient(DummyScraper):
        def detect_challenge(self, resp: FetchResponse) -> Challenge | None:
            return None

    page = response(status=403, text=json.dumps({"items": [], "next": None}))
    assert len(await crawl(Lenient(FakeFetcher({LAPTOP: page})), max_pages=1)) == 1


# --- fetch_detail ---------------------------------------------------------------------------


async def test_fetch_detail_parses_the_page_with_the_requested_url() -> None:
    url = f"{BASE}/p/mock-laptop-1"
    resp = FetchResponse(url=url, final_url=f"{url}?ref=x", status=200, text="<html/>")
    scraper, fetcher = make({url: resp})
    detail = await scraper.fetch_detail(url)
    assert str(detail.url) == url
    assert detail.raw_specs == {"html": "<html/>"}
    assert fetcher.requested == [url]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/p/1",
        "https://shop.example.evil.test/p/1",
        "/p/1",
        "ftp://shop.example/p",
    ],
)
async def test_fetch_detail_rejects_urls_outside_the_site_without_requesting(url: str) -> None:
    scraper, fetcher = make()
    with pytest.raises(ValueError):
        await scraper.fetch_detail(url)
    assert fetcher.requested == []


async def test_fetch_detail_raises_challenge_detected() -> None:
    url = f"{BASE}/p/mock-laptop-1"
    scraper, _ = make({url: response(url=url, status=403, text="")})
    with pytest.raises(ChallengeDetected):
        await scraper.fetch_detail(url)


# --- live_search ----------------------------------------------------------------------------


async def test_live_search_truncates_to_limit() -> None:
    scraper, fetcher = make({SEARCH: response(5, url=SEARCH)})
    items = await scraper.live_search("loa", 3)
    assert [i.title for i in items] == ["Mock Item 0", "Mock Item 1", "Mock Item 2"]
    assert fetcher.requested == [SEARCH]


async def test_live_search_items_use_the_other_category() -> None:
    scraper, _ = make({SEARCH: response(1, url=SEARCH)})
    (item,) = await scraper.live_search("loa", 10)
    assert item.category_hint is Category.other


@pytest.mark.parametrize(("query", "limit"), [("", 3), ("   ", 3), ("loa", 0), ("loa", -1)])
async def test_live_search_rejects_empty_query_or_bad_limit(query: str, limit: int) -> None:
    scraper, fetcher = make()
    with pytest.raises(ValueError):
        await scraper.live_search(query, limit)
    assert fetcher.requested == []


async def test_live_search_unsupported_site_raises_without_requesting() -> None:
    class NoLive(DummyScraper):
        config: ClassVar[SiteConfig] = SiteConfig(
            key=SiteKey.laptop88, base_url=BASE, min_delay_s=10
        )

    fetcher = FakeFetcher({})
    with pytest.raises(NotImplementedError):
        await NoLive(fetcher).live_search("loa", 3)
    assert fetcher.requested == []


async def test_live_search_raises_challenge_detected() -> None:
    scraper, _ = make({SEARCH: response(url=SEARCH, status=429, text="")})
    with pytest.raises(ChallengeDetected) as info:
        await scraper.live_search("loa", 3)
    assert info.value.challenge.kind is ChallengeKind.http_429


# --- biên bổ sung (từ review) -----------------------------------------------------------------


async def test_crawl_stops_when_next_url_points_back_to_an_already_fetched_page() -> None:
    scraper, fetcher = make({LAPTOP: response(1, PAGE2), PAGE2: response(1, PAGE2, url=PAGE2)})
    assert len(await crawl(scraper, max_pages=10)) == 2
    assert fetcher.requested == [LAPTOP, PAGE2]


async def test_crawl_builds_next_url_when_has_next_but_no_next_url() -> None:
    class NoNextUrl(DummyScraper):
        def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
            return ListingPage(has_next=page_url == LAPTOP)

    fetcher = FakeFetcher({LAPTOP: response(), PAGE2: response(url=PAGE2)})
    await crawl(NoNextUrl(fetcher), max_pages=5)
    assert fetcher.requested == [LAPTOP, PAGE2]


async def test_expect_items_does_not_flag_an_empty_page_when_resuming_after_page_one() -> None:
    page3 = f"{LAPTOP}?page=3"
    scraper, _ = make({page3: response(0, url=page3)})
    pages = await crawl(scraper, max_pages=5, start_page=3, expect_items=True)
    assert [len(p.items) for p in pages] == [0]


async def test_same_host_next_url_matches_regardless_of_case_and_requires_same_port() -> None:
    upper = "https://SHOP.example/c/laptop/p2"
    ported = "https://shop.example:8443/c/laptop/p2"
    page3 = f"{LAPTOP}?page=3"
    scraper, fetcher = make(
        {
            LAPTOP: response(1, upper),
            "https://shop.example/c/laptop/p2": response(1, ported, url=upper),
            page3: response(1, url=page3),
        }
    )
    await crawl(scraper, max_pages=3)
    # HttpUrl chuẩn hóa host thành chữ thường nên khớp; cổng khác thì bỏ next_url, dựng lại trang 3.
    assert fetcher.requested == [LAPTOP, "https://shop.example/c/laptop/p2", page3]
