"""Hàm thuần dựng CSV danh sách mua (X3, docs/07 §3.4)."""

import csv
import io
from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.catalog import OfferView, ShoppingListDetail, ShoppingListItemView
from app.domain.enums import PriceType, SiteKey, StockStatus
from app.services.list_export import (
    BOM,
    HEADER,
    TOTAL_LABEL,
    export_filename,
    render_list_csv,
    safe_text,
)

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def offer(price: int = 20_000_000, url: str = "https://mock.example/p/1") -> OfferView:
    return OfferView(
        offer_id=7,
        site=SiteKey.mockshop,
        title="Mock",
        url=url,
        price=price,
        effective_price=price,
        price_type=PriceType.regular,
        stock_status=StockStatus.in_stock,
        scraped_at=NOW,
    )


def item(**overrides: Any) -> ShoppingListItemView:
    data: dict[str, Any] = {
        "item_id": 1,
        "product_id": 1,
        "name": "Mock Laptop",
        "quantity": 2,
        "note": None,
        "preferred_offer_id": None,
        "price_at_add": 21_000_000,
        "current_price": 20_000_000,
        "price_delta": -1_000_000,
        "best_offer": offer(),
    }
    data.update(overrides)
    return ShoppingListItemView(**data)


def detail(items: list[ShoppingListItemView], total: int) -> ShoppingListDetail:
    return ShoppingListDetail(
        list_id=3,
        name="Mock",
        item_count=len(items),
        total_price=total,
        updated_at=NOW,
        items=items,
    )


def rows(text: str) -> list[list[str]]:
    assert text.startswith(BOM)
    return list(csv.reader(io.StringIO(text[len(BOM) :], newline="")))


def test_bom_header_crlf_and_one_row_per_item_then_total() -> None:
    text = render_list_csv(detail([item()], 40_000_000))
    assert BOM == "\N{ZERO WIDTH NO-BREAK SPACE}"
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    parsed = rows(text)
    assert parsed[0] == list(HEADER)
    assert parsed[1] == [
        "1",
        "Mock Laptop",
        "2",
        "21000000",
        "20000000",
        "-1000000",
        "40000000",
        "mockshop",
        "https://mock.example/p/1",
        "",
    ]
    assert parsed[2] == [TOTAL_LABEL, "", "", "", "", "", "40000000", "", "", ""]
    assert len(parsed) == 3


def test_empty_list_has_header_and_zero_total() -> None:
    parsed = rows(render_list_csv(detail([], 0)))
    assert parsed == [list(HEADER), [TOTAL_LABEL, "", "", "", "", "", "0", "", "", ""]]


def test_unavailable_item_leaves_price_site_and_link_blank() -> None:
    gone = item(current_price=None, price_delta=None, best_offer=None, note="hết hàng")
    parsed = rows(render_list_csv(detail([gone], 0)))
    assert parsed[1] == ["1", "Mock Laptop", "2", "21000000", "", "", "", "", "", "hết hàng"]


def test_missing_price_at_add_is_blank() -> None:
    parsed = rows(render_list_csv(detail([item(price_at_add=None, price_delta=None)], 1)))
    assert parsed[1][3] == "" and parsed[1][5] == ""


def test_numbered_rows_follow_item_order() -> None:
    items = [item(item_id=i, product_id=i, name=f"Mock {i}") for i in (5, 2, 9)]
    parsed = rows(render_list_csv(detail(items, 0)))
    assert [(row[0], row[1]) for row in parsed[1:4]] == [
        ("1", "Mock 5"),
        ("2", "Mock 2"),
        ("3", "Mock 9"),
    ]


def test_commas_quotes_and_newlines_round_trip() -> None:
    name = 'Mock "Pro", 16"'
    note = "dòng 1\ndòng 2, có phẩy"
    parsed = rows(render_list_csv(detail([item(name=name, note=note)], 0)))
    assert parsed[1][1] == name
    assert parsed[1][9] == note


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_formula_like_text_is_neutralised(prefix: str) -> None:
    payload = f'{prefix}HYPERLINK("https://evil.example")'
    parsed = rows(render_list_csv(detail([item(name=payload, note=payload)], 0)))
    assert parsed[1][1] == "'" + payload
    assert parsed[1][9] == "'" + payload


def test_negative_delta_stays_a_plain_number() -> None:
    parsed = rows(render_list_csv(detail([item()], 0)))
    assert parsed[1][5] == "-1000000"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), ("", ""), ("Mock", "Mock"), ("=1+1", "'=1+1"), ("a=b", "a=b")],
)
def test_safe_text(value: str | None, expected: str) -> None:
    assert safe_text(value) == expected


def test_export_filename() -> None:
    assert export_filename(42) == "danh-sach-42.csv"
