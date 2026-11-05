"""QA X3: test biên cho hàm thuần dựng CSV danh sách mua (docs/07 §3.4)."""

import csv
import io
import unicodedata
from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.catalog import OfferView, ShoppingListDetail, ShoppingListItemView
from app.domain.enums import PriceType, SiteKey, StockStatus
from app.services.list_export import BOM, HEADER, TOTAL_LABEL, render_list_csv, safe_text

NOW = datetime(2026, 11, 5, tzinfo=UTC)
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


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
        "quantity": 1,
        "note": None,
        "preferred_offer_id": None,
        "price_at_add": 20_000_000,
        "current_price": 20_000_000,
        "price_delta": 0,
        "best_offer": offer(),
    }
    data.update(overrides)
    return ShoppingListItemView(**data)


def detail(items: list[ShoppingListItemView], total: int | None = None) -> ShoppingListDetail:
    if total is None:
        total = sum(i.quantity * i.current_price for i in items if i.current_price is not None)
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


def test_vietnamese_nfc_nfd_and_emoji_survive_byte_for_byte_qa_x3() -> None:
    nfc = "Bàn phím cơ Mock Đỏ ấn tượng"
    nfd = unicodedata.normalize("NFD", nfc)
    emoji = "Mock 🎧 Tai nghe 👍🏽 家"
    items = [
        item(item_id=1, product_id=1, name=nfc),
        item(item_id=2, product_id=2, name=nfd, note=emoji),
    ]
    text = render_list_csv(detail(items))
    parsed = rows(text.encode("utf-8").decode("utf-8"))
    assert parsed[1][1] == nfc
    assert parsed[2][1] == nfd  # không tự chuẩn hóa: giữ đúng chuỗi trong DB
    assert parsed[2][9] == emoji


def test_bom_appears_exactly_once_at_start_qa_x3() -> None:
    text = render_list_csv(detail([item(note="ghi chú")]))
    assert text.count(BOM) == 1 and text.startswith(BOM)
    assert text.encode("utf-8").startswith(b"\xef\xbb\xbf")
    assert not text.encode("utf-8")[3:].startswith(b"\xef\xbb\xbf")


def test_long_note_with_separators_round_trips_qa_x3() -> None:
    note = ('Mock, "trích", dòng\r\nmới; ' * 40)[:500]
    assert len(note) == 500
    name = 'Laptop Mock 15.6", 16GB, "Pro"\r\nbản mới'
    parsed = rows(render_list_csv(detail([item(name=name, note=note)])))
    assert len(parsed) == 3  # header, mục, Tổng: xuống dòng trong ô không tách bản ghi
    assert parsed[1][1] == name
    assert parsed[1][9] == note


def test_url_with_comma_quote_semicolon_round_trips_qa_x3() -> None:
    url = 'https://mock.example/p/a,b;c?x="1"&y=2'
    parsed = rows(render_list_csv(detail([item(best_offer=offer(url=url))])))
    assert parsed[1][8] == url


def test_huge_quantity_line_total_is_exact_integer_qa_x3() -> None:
    quantity = 2_147_483_647
    price = 465  # 2_147_483_647 * 465 ≈ 9.99e11 ≤ 10^12
    line = quantity * price
    entry = item(
        quantity=quantity, price_at_add=price, current_price=price, best_offer=offer(price)
    )
    parsed = rows(render_list_csv(detail([entry])))
    assert parsed[1][6] == str(line)
    assert "e" not in parsed[1][6].lower() and "." not in parsed[1][6]
    assert parsed[2][6] == str(line)


def test_total_row_equals_sum_of_line_totals_skipping_unavailable_qa_x3() -> None:
    items = [
        item(item_id=1, product_id=1, quantity=3, current_price=1_990_000),
        item(item_id=2, product_id=2, current_price=None, price_delta=None, best_offer=None),
        item(item_id=3, product_id=3, quantity=2, current_price=27_490_000, price_delta=7_490_000),
    ]
    parsed = rows(render_list_csv(detail(items)))
    lines = [int(row[6]) for row in parsed[1:-1] if row[6]]
    assert parsed[-1][0] == TOTAL_LABEL
    assert int(parsed[-1][6]) == sum(lines) == 3 * 1_990_000 + 2 * 27_490_000
    assert [row[0] for row in parsed[1:-1]] == ["1", "2", "3"]


def test_every_row_has_same_column_count_qa_x3() -> None:
    items = [
        item(item_id=i, product_id=i, note=None if i % 2 else f"n{i}", name=f"Mock {i}")
        for i in range(1, 51)
    ]
    parsed = rows(render_list_csv(detail(items)))
    assert {len(row) for row in parsed} == {len(HEADER)}
    assert len(parsed) == 52


@pytest.mark.parametrize("payload", ["=1+1", "+1", "-1", "@SUM(A1)", "\t=1", "\r=1"])
def test_formula_prefix_applied_to_link_column_too_qa_x3(payload: str) -> None:
    # url là str tự do ở OfferView: dù DB chỉ có http(s), ô Link vẫn được chặn công thức.
    view = offer().model_copy(update={"url": payload})
    parsed = rows(render_list_csv(detail([item(best_offer=view)])))
    assert parsed[1][8] == "'" + payload


@pytest.mark.parametrize(
    "value",
    [
        " =1+1",  # khoảng trắng đầu: OWASP không liệt kê; Excel không coi là công thức
        "＝1+1",  # dấu bằng toàn hình
        "−1",  # dấu trừ Unicode
        "\n=1+1",  # LF đầu dòng (OWASP chỉ nêu tab và CR)
        "'=1+1",  # đã có nháy đơn
    ],
)
def test_non_owasp_prefixes_are_left_unchanged_qa_x3(value: str) -> None:
    """Ghi lại quyết định: chỉ 6 ký tự của OWASP được chặn; các biến thể này giữ nguyên."""
    assert safe_text(value) == value


def _excel_split(line: str, delimiter: str) -> list[str]:
    """Tách một dòng như Excel khi dấu phân cách danh sách là `delimiter` (tôn trọng nháy kép)."""
    cells: list[str] = []
    current = ""
    quoted = False
    for char in line:
        if char == '"':
            quoted = not quoted
            current += char
        elif char == delimiter and not quoted:
            cells.append(current)
            current = ""
        else:
            current += char
    cells.append(current)
    return [cell.strip('"') for cell in cells]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG-X3-1: ô văn bản chứa ';' không được bọc nháy kép, Excel vùng Việt Nam tách theo ';' "
        "(giới hạn đã ghi ở docs/07 §3.4) nên phần sau ';' thành ô mở đầu bằng '=' và chạy như "
        "công thức. OWASP khuyên bọc mọi ô văn bản trong nháy kép (QUOTE_ALL/QUOTE_NONNUMERIC)."
    ),
)
def test_semicolon_inside_text_cannot_start_a_formula_in_semicolon_locale_qa_x3() -> None:
    name = 'Mock Laptop;=HYPERLINK("https://evil.example","bấm")'
    note = "ghi chú;@SUM(1+1)"
    text = render_list_csv(detail([item(name=name, note=note)]))
    data_line = text[len(BOM) :].split("\r\n")[1]
    cells = _excel_split(data_line, ";")
    assert not [cell for cell in cells if cell.startswith(FORMULA_STARTS)], cells
