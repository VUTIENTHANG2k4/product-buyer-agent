"""Mock-shop (app/mock_shop): gọi qua ASGI transport, không mở cổng thật."""

import json
import re
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import httpx
import pytest

from app.mock_shop.catalog import PAGE_SIZE, fold, load_catalog, search
from app.mock_shop.main import COOKIE_NAME, create_app
from app.mock_shop.state import CODE_LENGTH, PASS_TTL_SECONDS, ShopState

BASE = "http://mock.test"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def client(clock: Clock) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(captcha_after=5, slow_seconds=0.01, clock=clock)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
        yield http


@pytest.fixture
async def open_client(clock: Clock) -> AsyncIterator[httpx.AsyncClient]:
    """Mock-shop gần như không bao giờ đòi captcha, để test phân trang không bị chặn."""
    app = create_app(captcha_after=10_000, slow_seconds=0.01, clock=clock)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
        yield http


def cards(page: str) -> list[str]:
    return re.findall(r'<li class="product-card" data-slug="([^"]+)"', page)


def json_ld(page: str) -> dict[str, object]:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    assert match
    data: dict[str, object] = json.loads(match.group(1))
    return data


def captcha_fields(page: str) -> tuple[str, str]:
    match = re.search(r'<div id="captcha" data-token="([^"]+)">([^<]+)</div>', page)
    assert match, "trang không có captcha"
    return match.group(1), match.group(2)


async def solve(client: httpx.AsyncClient, token: str, answer: str) -> httpx.Response:
    return await client.post(
        "/captcha",
        content=urlencode({"token": token, "answer": answer}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# --- Dữ liệu ----------------------------------------------------------------------------------


def test_catalog_has_60_fictional_products_across_four_categories() -> None:
    products = load_catalog()
    assert len(products) == 60
    assert {p.category for p in products} == {"laptop", "mouse", "keyboard", "headset"}
    assert all("Mock" in p.name for p in products)
    assert len({p.slug for p in products}) == 60


def test_catalog_covers_the_edge_cases_scrapers_must_handle() -> None:
    products = load_catalog()
    assert any(p.price is None for p in products)  # "Liên hệ"
    assert any(not p.in_stock for p in products)
    assert any(p.list_price and p.price and p.list_price > p.price for p in products)


def test_search_ignores_case_and_accents_and_needs_every_word() -> None:
    products = load_catalog()
    assert fold("Chuột ĐỎ") == "chuot do"
    assert search(products, "CHUOT logitech") and all(
        "logitech" in fold(p.name) and "chuot" in fold(p.name)
        for p in search(products, "CHUOT logitech")
    )
    assert search(products, "chuot khong-co-trong-du-lieu") == []
    assert search(products, "   ") == []


# --- robots.txt, phân trang -------------------------------------------------------------------


async def test_robots_txt_disallows_admin_and_has_no_crawl_delay(
    open_client: httpx.AsyncClient,
) -> None:
    response = await open_client.get("/robots.txt")
    assert response.text == "User-agent: *\nDisallow: /admin\n"
    assert "crawl-delay" not in response.text.lower()


async def test_listing_paginates_twelve_per_page_with_next_link(
    open_client: httpx.AsyncClient,
) -> None:
    first = (await open_client.get("/c/laptop")).text
    second = (await open_client.get("/c/laptop?page=2")).text
    third = (await open_client.get("/c/laptop?page=3")).text

    assert [len(cards(p)) for p in (first, second, third)] == [PAGE_SIZE, PAGE_SIZE, 2]
    assert 'rel="next" href="/c/laptop?page=2"' in first
    assert 'rel="next" href="/c/laptop?page=3"' in second
    assert 'rel="next"' not in third
    assert 'rel="prev" href="/c/laptop?page=2"' in third
    assert 'rel="prev"' not in first
    assert not set(cards(first)) & set(cards(second))


async def test_category_with_exactly_one_full_page_has_no_next_link(
    open_client: httpx.AsyncClient,
) -> None:
    page = (await open_client.get("/c/mouse")).text
    assert len(cards(page)) == PAGE_SIZE
    assert 'rel="next"' not in page


async def test_page_beyond_the_last_is_an_empty_list_without_next(
    open_client: httpx.AsyncClient,
) -> None:
    response = await open_client.get("/c/laptop?page=9")
    assert response.status_code == 200
    assert cards(response.text) == []
    assert 'rel="next"' not in response.text


async def test_unknown_category_is_404_and_invalid_page_is_422(
    open_client: httpx.AsyncClient,
) -> None:
    assert (await open_client.get("/c/phone")).status_code == 404
    assert (await open_client.get("/c/laptop?page=0")).status_code == 422
    assert (await open_client.get("/c/laptop?page=abc")).status_code == 422


async def test_every_listed_product_has_json_ld_matching_the_html_cards(
    open_client: httpx.AsyncClient,
) -> None:
    page = (await open_client.get("/c/keyboard")).text
    items = json_ld(page)["itemListElement"]
    assert isinstance(items, list)
    products = [item["item"] for item in items]
    assert [p["url"].rsplit("/", 1)[1] for p in products] == cards(page)
    first = products[0]
    assert first["@type"] == "Product"
    assert first["offers"]["priceCurrency"] == "VND"
    assert isinstance(first["offers"]["price"], int)
    assert first["url"].startswith(BASE)


async def test_prices_are_formatted_vietnamese_style_with_old_price_when_discounted(
    open_client: httpx.AsyncClient,
) -> None:
    page = (await open_client.get("/c/laptop")).text
    assert re.search(r'<span class="price">\d{1,3}(\.\d{3})+₫</span>', page)
    assert '<span class="old-price">' in page
    assert 'class="price price-contact">Liên hệ' in page
    assert 'class="stock out-of-stock">Hết hàng' in page


async def test_contact_price_product_has_no_offer_in_json_ld(
    open_client: httpx.AsyncClient,
) -> None:
    contact = next(p for p in load_catalog() if p.price is None)
    detail = json_ld((await open_client.get(f"/p/{contact.slug}")).text)
    assert "offers" not in detail


# --- Chi tiết, tìm kiếm -----------------------------------------------------------------------


async def test_detail_page_has_spec_table_and_product_json_ld(
    open_client: httpx.AsyncClient,
) -> None:
    product = next(p for p in load_catalog() if p.category == "laptop" and p.price)
    page = (await open_client.get(f"/p/{product.slug}")).text

    ld = json_ld(page)
    assert (ld["@type"], ld["name"], ld["sku"]) == ("Product", product.name, product.sku)
    assert ld["brand"] == {"@type": "Brand", "name": product.brand}
    assert "<th>CPU</th>" in page and '<table class="specs">' in page
    assert len(re.findall(r"<tr><th>", page)) == len(product.specs)


async def test_out_of_stock_detail_reports_out_of_stock_availability(
    open_client: httpx.AsyncClient,
) -> None:
    product = next(p for p in load_catalog() if not p.in_stock and p.price)
    ld = json_ld((await open_client.get(f"/p/{product.slug}")).text)
    offers = ld["offers"]
    assert isinstance(offers, dict)
    assert offers["availability"].endswith("OutOfStock")


async def test_unknown_product_is_404(open_client: httpx.AsyncClient) -> None:
    response = await open_client.get("/p/khong-co")
    assert response.status_code == 404


async def test_search_returns_matching_products_ignoring_accents(
    open_client: httpx.AsyncClient,
) -> None:
    page = (await open_client.get("/search", params={"q": "chuot razer"})).text
    slugs = cards(page)
    assert slugs
    names = {p.slug: p.name for p in load_catalog()}
    assert all("razer" in names[s].lower() and "chuột" in names[s].lower() for s in slugs)


async def test_search_without_query_or_matches_is_an_empty_list(
    open_client: httpx.AsyncClient,
) -> None:
    for params in ({}, {"q": ""}, {"q": "không-có-gì-khớp"}):
        response = await open_client.get("/search", params=params)
        assert response.status_code == 200
        assert cards(response.text) == []


async def test_names_with_html_special_characters_are_escaped(
    open_client: httpx.AsyncClient,
) -> None:
    page = (await open_client.get("/search", params={"q": "<script>alert(1)</script>"})).text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# --- Captcha giả ------------------------------------------------------------------------------


async def test_captcha_appears_after_n_requests_and_blocks_every_page(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(5):
        assert 'id="captcha"' not in (await client.get("/c/laptop")).text

    for path in ("/c/laptop", "/c/mouse?page=2", "/search?q=chuot", "/p/bat-ky"):
        page = (await client.get(path)).text
        token, code = captcha_fields(page)
        assert len(code) == CODE_LENGTH
        assert token
    assert '<form method="post" action="/captcha">' in page


async def test_robots_txt_and_control_do_not_count_towards_captcha(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(20):
        await client.get("/robots.txt")
    assert 'id="captcha"' not in (await client.get("/c/laptop")).text


async def test_challenge_code_stays_the_same_until_solved(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        await client.get("/c/laptop")
    first = captcha_fields((await client.get("/c/laptop")).text)
    second = captcha_fields((await client.get("/c/mouse")).text)
    assert first == second


async def test_correct_answer_sets_cookie_and_unblocks_the_shop(
    client: httpx.AsyncClient, clock: Clock
) -> None:
    for _ in range(5):
        await client.get("/c/laptop")
    token, code = captcha_fields((await client.get("/c/laptop")).text)

    response = await solve(client, token, code.lower())  # không phân biệt hoa thường

    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"]
    assert cookie_header.startswith(f"{COOKIE_NAME}=")
    assert f"Max-Age={PASS_TTL_SECONDS}" in cookie_header
    for _ in range(30):  # có cookie thì không bị đếm nữa
        assert 'id="captcha"' not in (await client.get("/c/laptop")).text


async def test_wrong_answer_is_400_and_the_challenge_remains(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        await client.get("/c/laptop")
    token, code = captcha_fields((await client.get("/c/laptop")).text)

    for bad in ("ZZZZZ", "", code[:-1]):
        response = await solve(client, token, bad)
        assert response.status_code == 400
        assert "set-cookie" not in response.headers

    assert captcha_fields((await client.get("/c/laptop")).text) == (token, code)


async def test_wrong_token_or_no_pending_challenge_is_rejected(client: httpx.AsyncClient) -> None:
    assert (await solve(client, "x", "ABCDE")).status_code == 400  # chưa có challenge
    for _ in range(5):
        await client.get("/c/laptop")
    _, code = captcha_fields((await client.get("/c/laptop")).text)
    assert (await solve(client, "token-sai", code)).status_code == 400


async def test_cookie_expires_after_ten_minutes(client: httpx.AsyncClient, clock: Clock) -> None:
    for _ in range(5):
        await client.get("/c/laptop")
    token, code = captcha_fields((await client.get("/c/laptop")).text)
    await solve(client, token, code)
    assert 'id="captcha"' not in (await client.get("/c/laptop")).text

    clock.now += PASS_TTL_SECONDS + 1
    for _ in range(5):  # sau khi hết hạn lại được `captcha_after` request rồi bị chặn
        assert 'id="captcha"' not in (await client.get("/c/laptop")).text
    assert 'id="captcha"' in (await client.get("/c/laptop")).text


async def test_a_forged_cookie_does_not_bypass_the_captcha(client: httpx.AsyncClient) -> None:
    client.cookies.set(COOKIE_NAME, "forged", domain="mock.test")
    for _ in range(5):
        await client.get("/c/laptop")
    assert 'id="captcha"' in (await client.get("/c/laptop")).text


async def test_reset_clears_counter_challenge_and_cookies(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        await client.get("/c/laptop")
    token, code = captcha_fields((await client.get("/c/laptop")).text)
    await solve(client, token, code)

    assert (await client.get("/__control/reset")).json() == {"status": "reset"}

    for _ in range(5):
        assert 'id="captcha"' not in (await client.get("/c/laptop")).text
    assert 'id="captcha"' in (await client.get("/c/laptop")).text


async def test_each_app_has_its_own_state(clock: Clock) -> None:
    one, two = create_app(captcha_after=1, clock=clock), create_app(captcha_after=1, clock=clock)
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=one), base_url=BASE) as a,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=two), base_url=BASE) as b,
    ):
        await a.get("/c/laptop")
        assert 'id="captcha"' in (await a.get("/c/laptop")).text
        assert 'id="captcha"' not in (await b.get("/c/laptop")).text


def test_captcha_after_must_be_positive() -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError, match="captcha_after"):
            ShopState(captcha_after=bad)
    with pytest.raises(ValueError, match="captcha_after"):
        create_app(captcha_after=0)


def test_default_captcha_threshold_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_SHOP_CAPTCHA_AFTER", "3")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        state: ShopState = create_app().state.shop
        assert state.captcha_after == 3
    finally:
        get_settings.cache_clear()


# --- Chế độ lỗi -------------------------------------------------------------------------------


async def test_fail_500_returns_a_server_error(open_client: httpx.AsyncClient) -> None:
    for path in ("/c/laptop?fail=500", "/search?q=a&fail=500"):
        assert (await open_client.get(path)).status_code == 500


async def test_fail_empty_returns_200_with_no_products_and_no_next(
    open_client: httpx.AsyncClient,
) -> None:
    response = await open_client.get("/c/laptop?fail=empty")
    assert response.status_code == 200
    assert cards(response.text) == []
    assert 'rel="next"' not in response.text


async def test_fail_slow_still_returns_the_page_after_the_delay(
    open_client: httpx.AsyncClient,
) -> None:
    app = create_app(captcha_after=100, slow_seconds=0.01)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as slow:
        response = await slow.get("/c/laptop?fail=slow")
    assert response.status_code == 200
    assert len(cards(response.text)) == PAGE_SIZE


async def test_unknown_fail_mode_is_rejected(open_client: httpx.AsyncClient) -> None:
    assert (await open_client.get("/c/laptop?fail=boom")).status_code == 422


async def test_fail_mode_is_kept_in_pagination_links(open_client: httpx.AsyncClient) -> None:
    page = (await open_client.get("/c/laptop?fail=slow")).text
    assert 'href="/c/laptop?page=2&amp;fail=slow"' in page
