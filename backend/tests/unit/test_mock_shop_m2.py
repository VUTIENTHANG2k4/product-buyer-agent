"""QA M2: mock-shop với đầu vào lạ (app/mock_shop). ASGI transport, đồng hồ giả, không mạng."""

import re
import unicodedata
from collections.abc import AsyncIterator
from urllib.parse import quote, urlencode

import httpx
import pytest

from app.mock_shop.main import COOKIE_NAME, create_app
from app.mock_shop.state import PASS_TTL_SECONDS

BASE = "http://mock.test"
SLUG = "asus-mock-strix-15-x01-mk-la001"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make_client(app_clock: Clock, captcha_after: int) -> httpx.AsyncClient:
    app = create_app(captcha_after=captcha_after, slow_seconds=0.01, clock=app_clock)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


@pytest.fixture
async def open_shop(clock: Clock) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(clock, 10_000) as client:
        yield client


@pytest.fixture
async def strict_shop(clock: Clock) -> AsyncIterator[httpx.AsyncClient]:
    """Captcha ngay từ request thứ hai."""
    async with make_client(clock, 1) as client:
        yield client


def captcha_of(page: str) -> tuple[str, str]:
    match = re.search(r'<div id="captcha" data-token="([^"]+)">([^<]+)</div>', page)
    assert match, "trang không có captcha"
    return match.group(1), match.group(2)


async def post_answer(client: httpx.AsyncClient, token: str, answer: str) -> httpx.Response:
    return await client.post(
        "/captcha",
        content=urlencode({"token": token, "answer": answer}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


async def trigger_captcha(client: httpx.AsyncClient) -> tuple[str, str]:
    for _ in range(3):
        page = (await client.get("/c/laptop")).text
        if 'id="captcha"' in page:
            return captcha_of(page)
    raise AssertionError("captcha không xuất hiện")


# --- đầu vào lạ -------------------------------------------------------------------------------


async def test_the_page_parameter_accepts_10000_as_an_empty_last_page_and_rejects_beyond(
    open_shop: httpx.AsyncClient,
) -> None:
    far = await open_shop.get("/c/laptop", params={"page": 10_000})
    assert far.status_code == 200
    assert 'class="product-card"' not in far.text and 'rel="next"' not in far.text

    for bad in ("10001", "0", "-1", "abc", "", "%D9%A1"):
        assert (await open_shop.get(f"/c/laptop?page={bad}")).status_code == 422, bad


async def test_search_query_is_escaped_and_nfd_equals_nfc(open_shop: httpx.AsyncClient) -> None:
    hostile = await open_shop.get("/search", params={"q": "<script>alert(1)</script>"})
    assert hostile.status_code == 200
    assert "<script>alert(1)</script>" not in hostile.text
    assert "&lt;script&gt;" in hostile.text

    word = "chuột"
    nfc = await open_shop.get(f"/search?q={quote(unicodedata.normalize('NFC', word))}")
    nfd = await open_shop.get(f"/search?q={quote(unicodedata.normalize('NFD', word))}")
    plain = await open_shop.get("/search?q=chuot")
    cards = lambda r: re.findall(r'data-slug="([^"]+)"', r.text)  # noqa: E731
    assert cards(nfc) and cards(nfc) == cards(nfd) == cards(plain)


async def test_search_query_length_limit_and_odd_bytes_never_cause_a_server_error(
    open_shop: httpx.AsyncClient,
) -> None:
    assert (await open_shop.get("/search", params={"q": "a" * 200})).status_code == 200
    assert (await open_shop.get("/search", params={"q": "a" * 201})).status_code == 422
    for raw in ("%00", "%FF", "%C0%AF", "%ED%A0%80", "+++", "%E2%80%8B"):
        assert (await open_shop.get(f"/search?q={raw}")).status_code == 200, raw


async def test_path_tricks_in_the_slug_never_reach_the_filesystem_or_crash(
    open_shop: httpx.AsyncClient,
) -> None:
    for slug in ("..", "%2e%2e", "..%2F..%2Fetc%2Fpasswd", "a%00b", SLUG.upper()):
        response = await open_shop.get(f"/p/{slug}")
        assert response.status_code == 404, slug
    redirected = await open_shop.get("/p/%2e%2e%2f")  # Starlette chuẩn hóa dấu '/' cuối
    assert redirected.status_code in (307, 404)
    assert (await open_shop.get(f"/p/{SLUG}")).status_code == 200


# --- POST /captcha ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        pytest.param(b"", None, id="empty"),
        pytest.param(b"\xff\xfe\x00\x80", "application/x-www-form-urlencoded", id="not-utf8"),
        pytest.param(b'{"token": "x", "answer": "y"}', "application/json", id="json"),
        pytest.param(b"token=only-token", "application/x-www-form-urlencoded", id="no-answer"),
        pytest.param(b"answer=ONLYA", "application/x-www-form-urlencoded", id="no-token"),
        pytest.param(b"token=a&token=b&answer=c", "application/x-www-form-urlencoded", id="dup"),
        pytest.param(b"x" * 2_000_000, "application/x-www-form-urlencoded", id="2mb"),
    ],
)
async def test_malformed_captcha_posts_are_400_and_do_not_consume_the_challenge(
    strict_shop: httpx.AsyncClient, body: bytes, content_type: str | None
) -> None:
    token, code = await trigger_captcha(strict_shop)

    headers = {"Content-Type": content_type} if content_type else {}
    bad = await strict_shop.post("/captcha", content=body, headers=headers)

    assert bad.status_code == 400
    assert COOKIE_NAME not in bad.headers.get("set-cookie", "")
    good = await post_answer(strict_shop, token, code)  # thử đúng vẫn qua được
    assert good.status_code == 200 and COOKIE_NAME in good.headers["set-cookie"]


async def test_a_solved_token_cannot_be_replayed_and_the_next_challenge_has_a_new_token(
    strict_shop: httpx.AsyncClient,
) -> None:
    token, code = await trigger_captcha(strict_shop)
    assert (
        await post_answer(strict_shop, token, code.lower())
    ).status_code == 200  # không phân biệt hoa

    replay = await post_answer(strict_shop, token, code)
    assert replay.status_code == 400 and "set-cookie" not in replay.headers

    strict_shop.cookies.clear()  # máy khác, chưa có cookie: phải đếm lại từ 0
    second_token, second_code = await trigger_captcha(strict_shop)
    assert second_token != token
    assert (await post_answer(strict_shop, token, second_code)).status_code == 400  # token cũ
    if code != second_code:
        assert (await post_answer(strict_shop, second_token, code)).status_code == 400
    assert (await post_answer(strict_shop, second_token, second_code)).status_code == 200


async def test_the_pass_cookie_is_valid_up_to_but_not_including_the_ttl(
    strict_shop: httpx.AsyncClient, clock: Clock
) -> None:
    token, code = await trigger_captcha(strict_shop)
    assert (await post_answer(strict_shop, token, code)).status_code == 200

    clock.now += PASS_TTL_SECONDS - 0.001
    for _ in range(4):  # còn hiệu lực: không bao giờ bị đếm hay chặn
        assert 'id="captcha"' not in (await strict_shop.get("/c/laptop")).text

    clock.now += 0.001  # đúng mốc hết hạn: cookie vô hiệu, bộ đếm chạy lại từ 0
    pages = [(await strict_shop.get("/c/laptop")).text for _ in range(3)]
    assert any('id="captcha"' in page for page in pages)


async def test_failure_modes_do_not_bypass_the_captcha_gate_but_invalid_ones_are_422(
    strict_shop: httpx.AsyncClient,
) -> None:
    await trigger_captcha(strict_shop)

    for query in ("fail=500", "fail=slow", "fail=empty"):
        blocked = await strict_shop.get(f"/p/{SLUG}?{query}")
        assert blocked.status_code == 200 and 'id="captcha"' in blocked.text, query
    assert (await strict_shop.get(f"/p/{SLUG}?fail=bogus")).status_code == 422
