"""clean_url (app/normalize/url.py)."""

import pytest

from app.normalize.url import MAX_URL_LENGTH, clean_url

BASE = "https://shop.example/laptop/asus-fx608"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (BASE, BASE),
        (f"{BASE}?utm_source=fb&utm_medium=cpc", BASE),
        (f"{BASE}?fbclid=abc&gclid=1&srsltid=x", BASE),
        (f"{BASE}?color=black&utm_campaign=a", f"{BASE}?color=black"),
        (f"{BASE}?UTM_Source=a&Color=Red", f"{BASE}?Color=Red"),
        (f"{BASE}#reviews", BASE),
        (f"{BASE}?a=1#x", f"{BASE}?a=1"),
        ("https://user:pw@shop.example/p/1", "https://shop.example/p/1"),
        ("HTTPS://Shop.Example/Path/Case", "https://shop.example/Path/Case"),
        ("http://shop.example:8100/p/1", "http://shop.example:8100/p/1"),
        ("  https://shop.example/p/1  ", "https://shop.example/p/1"),
        ("https://shop.example/p/1?q=", "https://shop.example/p/1?q="),
        ("https://[::1]:8100/p/1", "https://[::1]:8100/p/1"),
    ],
)
def test_removes_tracking_credentials_and_fragment(raw: str, expected: str) -> None:
    assert clean_url(raw) == expected


def test_is_idempotent() -> None:
    once = clean_url(f"{BASE}?utm_source=x&b=2&a=1#f")
    assert clean_url(once) == once


@pytest.mark.parametrize(
    "raw",
    ["", "ftp://shop.example/p", "/relative/path", "shop.example/p", "https://", "javascript:1"],
)
def test_rejects_non_http_absolute_urls(raw: str) -> None:
    with pytest.raises(ValueError, match="URL"):
        clean_url(raw)


def test_length_limit_is_inclusive() -> None:
    prefix = "https://shop.example/"
    assert len(clean_url(prefix + "a" * (MAX_URL_LENGTH - len(prefix)))) == MAX_URL_LENGTH
    with pytest.raises(ValueError, match="longer"):
        clean_url(prefix + "a" * (MAX_URL_LENGTH - len(prefix) + 1))
