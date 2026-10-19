"""M3b/T2.7e: `clean_url` giữ mã hóa query gốc và coi thứ tự tham số là một khóa."""

import pytest

from app.normalize.url import clean_url

BASE = "https://shop.example/p"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(f"{BASE}?q=a%20b", f"{BASE}?q=a%20b", id="percent-20-kept"),
        pytest.param(f"{BASE}?q=a+b", f"{BASE}?q=a+b", id="plus-kept"),
        pytest.param(f"{BASE}?q=a%2Bb", f"{BASE}?q=a%2Bb", id="encoded-plus-kept"),
        pytest.param(f"{BASE}?q=%c3%a9", f"{BASE}?q=%C3%A9", id="hex-upper-cased"),
        pytest.param(f"{BASE}?b=2&a=1", f"{BASE}?a=1&b=2", id="sorted-by-name"),
        pytest.param(f"{BASE}?a=1&b=2", f"{BASE}?a=1&b=2", id="already-sorted"),
        pytest.param(f"{BASE}?z=1&a=2&a=1", f"{BASE}?a=2&a=1&z=1", id="repeated-name-keeps-order"),
        pytest.param(
            f"{BASE}?b=2&utm_source=x&a=1&fbclid=9", f"{BASE}?a=1&b=2", id="tracking-gone"
        ),
        pytest.param(f"{BASE}?a=1&&b=2&", f"{BASE}?a=1&b=2", id="empty-segments-dropped"),
        pytest.param(f"{BASE}?flag&a=1", f"{BASE}?a=1&flag=", id="bare-name-gets-equals"),
        pytest.param(f"{BASE}?q=", f"{BASE}?q=", id="blank-value-kept"),
        pytest.param(
            f"{BASE}?filter[price]=1&a=2", f"{BASE}?a=2&filter[price]=1", id="brackets-kept"
        ),
        pytest.param(f"{BASE}?q=é", f"{BASE}?q=%C3%A9", id="non-ascii-percent-encoded"),
        pytest.param(f"{BASE}?q=a=b", f"{BASE}?q=a=b", id="equals-in-value"),
        pytest.param(f"{BASE}?utm%5Fsource=x&a=1", f"{BASE}?a=1", id="encoded-tracking-name"),
    ],
)
def test_query_keeps_its_original_encoding_and_is_ordered_by_name(raw: str, expected: str) -> None:
    assert clean_url(raw) == expected


def test_both_orders_of_the_same_parameters_are_one_key() -> None:
    assert clean_url(f"{BASE}?a=1&b=2") == clean_url(f"{BASE}?b=2&a=1")


def test_hex_digits_in_either_case_are_one_key() -> None:
    assert (
        clean_url(f"{BASE}?q=%c3%a9") == clean_url(f"{BASE}?q=%C3%A9") == clean_url(f"{BASE}?q=é")
    )


def test_space_and_plus_encodings_stay_distinct_keys() -> None:
    assert clean_url(f"{BASE}?q=a%20b") != clean_url(f"{BASE}?q=a+b")


@pytest.mark.parametrize(
    "raw",
    [f"{BASE}?z=%20&a=é&utm_x=1&m", f"{BASE}?b=2&a=1&b=1", f"{BASE}?q=a%2Bb+c%20d"],
)
def test_cleaning_twice_changes_nothing(raw: str) -> None:
    once = clean_url(raw)

    assert clean_url(once) == once
