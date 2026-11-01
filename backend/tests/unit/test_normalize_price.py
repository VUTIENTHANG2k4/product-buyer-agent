"""parse_price (app/normalize/price.py)."""

import logging

import pytest

from app.normalize.price import MAX_PRICE_VND, MIN_PRICE_VND, parse_price


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("27.490.000₫", 27_490_000),
        ("27,490,000 đ", 27_490_000),
        ("27 490 000đ", 27_490_000),
        ("27490000", 27_490_000),
        ("  1.290.000 VNĐ  ", 1_290_000),
        ("Từ 15.990.000₫", 15_990_000),
        ("27.490.000,50 đ", 27_490_000),
        ("27,490,000.50", 27_490_000),
        ("990.000đ", 990_000),
        (12_900_000, 12_900_000),
        (str(MIN_PRICE_VND), MIN_PRICE_VND),
        (str(MAX_PRICE_VND), MAX_PRICE_VND),
    ],
)
def test_parses_vietnamese_price_formats(raw: str | int, expected: int) -> None:
    assert parse_price(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["27.49*.000", "***.000đ", "? ₫", "Liên hệ", "", "   ", "₫", "abc", None, True, "1.5", "0"],
)
def test_masked_unreadable_or_non_price_values_are_none(raw: str | bool | None) -> None:
    assert parse_price(raw) is None


@pytest.mark.parametrize("raw", ["9.999", "0 đ", "500.000.001", "99.999.999.999", 9_999, -5, 0])
def test_out_of_range_prices_are_none_and_logged(
    raw: str | int, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.normalize.price"):
        assert parse_price(raw) is None
    assert caplog.records


def test_result_is_a_plain_int() -> None:
    assert type(parse_price("27.490.000₫")) is int


def test_masked_price_is_not_logged_as_out_of_range(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.normalize.price"):
        assert parse_price("2*.000.000") is None
    assert not caplog.records
