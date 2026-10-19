"""M3b/T2.7b: Fetcher từ chối thân phản hồi lớn hơn 5 MB (sau giải nén), không ghi raw cache."""

import gzip
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from app.scrapers.http.errors import ResponseTooLarge, RobotsUnavailable
from app.scrapers.http.fetcher import MAX_RESPONSE_BYTES
from tests.unit.test_fetcher import SHOP, FakeTime, make_fetcher

PAGE = f"{SHOP}/p"
ROBOTS = f"{SHOP}/robots.txt"


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.get(ROBOTS).respond(404)
        yield router


def cached_files(directory: Path) -> list[Path]:
    return [path for path in directory.rglob("*") if path.is_file()]


async def test_a_body_of_exactly_the_limit_is_accepted(
    http: respx.MockRouter, fake_time: FakeTime, tmp_path: Path
) -> None:
    http.get(PAGE).respond(200, content=b"a" * MAX_RESPONSE_BYTES)

    response = await make_fetcher(fake_time, raw_cache_dir=tmp_path).get(PAGE)

    assert len(response.text) == MAX_RESPONSE_BYTES
    assert len(cached_files(tmp_path)) == 1


async def test_one_byte_over_the_limit_is_rejected_and_nothing_is_cached(
    http: respx.MockRouter, fake_time: FakeTime, tmp_path: Path
) -> None:
    page = http.get(PAGE).respond(200, content=b"a" * (MAX_RESPONSE_BYTES + 1))

    with pytest.raises(ResponseTooLarge) as error:
        await make_fetcher(fake_time, raw_cache_dir=tmp_path).get(PAGE)

    assert error.value.url == PAGE
    assert page.call_count == 1  # không retry
    assert fake_time.sleeps == [5.0]  # chỉ độ trễ giữa robots.txt và trang, không backoff
    assert cached_files(tmp_path) == []


async def test_an_honest_content_length_over_the_limit_is_rejected_before_reading(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(PAGE).respond(
        200, content=b"x" * 10, headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}
    )

    with pytest.raises(ResponseTooLarge, match="Content-Length"):
        await make_fetcher(fake_time).get(PAGE)


async def test_a_lying_small_content_length_does_not_bypass_the_limit(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(PAGE).respond(
        200, content=b"a" * (MAX_RESPONSE_BYTES + 10), headers={"Content-Length": "10"}
    )

    with pytest.raises(ResponseTooLarge, match="exceeds"):
        await make_fetcher(fake_time).get(PAGE)


async def test_a_gzip_bomb_is_measured_after_decompression(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    bomb = gzip.compress(b"\0" * (MAX_RESPONSE_BYTES + 1))
    assert len(bomb) < 100_000
    http.get(PAGE).mock(
        return_value=httpx.Response(
            200, content=bomb, headers={"Content-Encoding": "gzip", "Content-Type": "text/html"}
        )
    )

    with pytest.raises(ResponseTooLarge):
        await make_fetcher(fake_time).get(PAGE)


async def test_a_normal_gzip_response_is_still_decoded_with_its_charset(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    body = "<p>Máy tính Mock xách tay</p>".encode()
    http.get(PAGE).mock(
        return_value=httpx.Response(
            200,
            content=gzip.compress(body),
            headers={"Content-Encoding": "gzip", "Content-Type": "text/html; charset=utf-8"},
        )
    )

    response = await make_fetcher(fake_time).get(PAGE)

    assert response.text == body.decode()
    assert response.status == 200


async def test_headers_other_than_the_body_ones_survive_the_rebuild(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(PAGE).respond(
        403, text="no", headers={"Server": "cloudflare", "cf-mitigated": "challenge"}
    )

    response = await make_fetcher(fake_time).get(PAGE)

    assert response.status == 403
    assert response.headers["cf-mitigated"] == "challenge"
    assert response.headers["content-length"] == "2"  # độ dài thân đã đọc, không phải bản gốc


async def test_an_oversized_robots_txt_is_unavailable_not_a_crash(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(ROBOTS).respond(200, content=b"#" * (MAX_RESPONSE_BYTES + 1))
    page = http.get(PAGE).respond(200)

    with pytest.raises(RobotsUnavailable):
        await make_fetcher(fake_time).get(PAGE)

    assert page.call_count == 0
