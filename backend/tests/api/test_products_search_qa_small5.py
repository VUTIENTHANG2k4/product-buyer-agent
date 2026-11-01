"""QA small-fixes-5: `GET /products?q=` không phân biệt dấu (BUG-M7-3, `unaccent`, migration 0006).

Biên: `q` rỗng/rất dài/chứa NUL/Unicode lạ, đủ bộ chữ cái tiếng Việt, tên lưu ở dạng NFD, kết hợp
với bộ lọc + phân trang, nhiều từ khóa. Test `xfail(strict=True)` mã `BUG-S5-n` là lỗi đã tái hiện:
khi sửa xong, XPASS làm test đỏ và phải gỡ dấu xfail.
"""

import time
import unicodedata
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.domain.enums import Category
from tests.service_support import add_offer, add_product

# 12 nguyên âm x 6 thanh + chữ có dấu riêng của tiếng Việt, kèm chữ cái gốc tương ứng.
VIETNAMESE_BASE: dict[str, str] = {
    **dict.fromkeys("àáảãạăằắẳẵặâầấẩẫậ", "a"),
    **dict.fromkeys("èéẻẽẹêềếểễệ", "e"),
    **dict.fromkeys("ìíỉĩị", "i"),
    **dict.fromkeys("òóỏõọôồốổỗộơờớởỡợ", "o"),
    **dict.fromkeys("ùúủũụưừứửữự", "u"),
    **dict.fromkeys("ỳýỷỹỵ", "y"),
    "đ": "d",
}


def total(client: TestClient, **params: Any) -> int:
    response = client.get("/api/products", params=params)
    assert response.status_code == 200, response.text
    return int(response.json()["total"])


def names(client: TestClient, **params: Any) -> list[str]:
    response = client.get("/api/products", params=params)
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["items"]]


def stock(session: Session, name: str, price: int = 1_000_000, **overrides: Any) -> int:
    product = add_product(session, canonical_name=name, **overrides)
    add_offer(session, product, price=price)
    assert product.id is not None
    return product.id


# ---------------------------------------------------------------- q rỗng / khoảng trắng
@pytest.mark.parametrize("q", ["", " ", "   ", "\t", "\n", "　", "   "])
def test_a_blank_query_applies_no_text_filter(
    client: TestClient, db_session: Session, q: str
) -> None:
    stock(db_session, "Chuột Mock A")
    stock(db_session, "Bàn phím Mock B")

    assert total(client, q=q) == 2


@pytest.mark.parametrize("q", ["chuot", "  chuot  ", "chuot ", "\tchuot\n", "chuot\x00"])
def test_surrounding_whitespace_and_nul_do_not_change_the_match(
    client: TestClient, db_session: Session, q: str
) -> None:
    stock(db_session, "Chuột Mock A")
    stock(db_session, "Bàn phím Mock B")

    assert total(client, q=q) == 1


def test_a_nul_in_the_middle_of_a_word_is_dropped_before_matching(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Mock A")

    assert total(client, q="chu\x00ot") == 1


# ---------------------------------------------------------------- độ dài
def test_a_two_hundred_character_query_is_accepted_and_matches_nothing(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Mock A")

    assert total(client, q="a" * 200) == 0


def test_a_query_over_two_hundred_characters_is_a_clean_422(
    client: TestClient, db_session: Session
) -> None:
    response = client.get("/api/products", params={"q": "a" * 201})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_long_accented_product_name_is_found_by_a_late_unaccented_word(
    client: TestClient, db_session: Session
) -> None:
    name = " ".join(["Chuột"] * 300) + " Cường"
    stock(db_session, name)

    assert total(client, q="cuong") == 1


def test_a_hundred_one_letter_terms_finish_quickly_and_all_must_match(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Mock A")
    q = " ".join(["c"] * 100)

    started = time.perf_counter()
    result = total(client, q=q)

    assert result == 1
    assert time.perf_counter() - started < 5.0


# ---------------------------------------------------------------- Unicode lạ
@pytest.mark.parametrize(
    ("name", "q"),
    [
        ("Chuột 漢字 Mock", "漢字"),
        ("Chuột 🎮 Mock", "🎮"),
        ("Chuột Mock ½", "1⁄2"),
        ("Chuột Mock ǆ", "dz"),
        ("Chuột Mock ǆ", "ǆ"),
        ("Chuột Mock Ǆ", "ǆ"),
        ("Chuột Mock ß", "ss"),
        ("Chuột Mock Æ", "ae"),
        ("Chuột Mock Ł", "l"),
        ("Chuột Mock Ø", "o"),
        ("Chuột Mock ﬁ", "fi"),
    ],
)
def test_exotic_unicode_in_names_and_queries_matches_after_folding(
    client: TestClient, db_session: Session, name: str, q: str
) -> None:
    stock(db_session, name)

    assert total(client, q=q) == 1


@pytest.mark.parametrize("q", ["́", "̣́", "á́́", "​", "﻿"])
def test_stray_combining_marks_and_invisible_characters_never_cause_an_error(
    client: TestClient, db_session: Session, q: str
) -> None:
    stock(db_session, "Chuột Mock A")

    response = client.get("/api/products", params={"q": q})

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("q", ["\\", "%", "_", "\\%", "%%", "__", "\\\\", "' OR 1=1 --", '";--'])
def test_sql_and_like_metacharacters_are_literal_and_match_nothing(
    client: TestClient, db_session: Session, q: str
) -> None:
    stock(db_session, "Chuột Mock A")

    assert total(client, q=q) == 0


# ---------------------------------------------------------------- đủ bộ chữ cái tiếng Việt
def test_every_vietnamese_letter_matches_by_itself_and_by_its_base_letter(
    client: TestClient, db_session: Session
) -> None:
    # Mỗi chữ nằm trong một từ riêng "zxzx{chữ}zxzx": từ gốc "zxzxazxzx" không có sẵn trong dữ liệu.
    letters = list(VIETNAMESE_BASE)
    name = "Mock " + " ".join(f"zx{letter}zx" for letter in letters)
    stock(db_session, name)

    missing: list[str] = []
    for letter, base in VIETNAMESE_BASE.items():
        for q in (f"zx{letter}zx", f"zx{base}zx", f"ZX{letter.upper()}ZX", f"zx{base.upper()}zx"):
            if total(client, q=q) != 1:
                missing.append(f"{letter}:{q}")
    assert missing == []


def test_a_letter_with_a_different_base_does_not_match(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Mock zxàzx")

    assert [total(client, q=q) for q in ("zxezx", "zxôzx", "zxdzx")] == [0, 0, 0]


@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_stored_names_in_any_normal_form_are_found_by_a_plain_ascii_query(
    client: TestClient, db_session: Session, form: Literal["NFC", "NFD", "NFKC", "NFKD"]
) -> None:
    stock(db_session, unicodedata.normalize(form, "Chuột không dây Mượt Mock"))

    assert [total(client, q=q) for q in ("chuot khong day muot", "CHUOT", "muot")] == [1, 1, 1]


@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_queries_in_any_normal_form_find_a_composed_name(
    client: TestClient, db_session: Session, form: Literal["NFC", "NFD", "NFKC", "NFKD"]
) -> None:
    stock(db_session, "Chuột không dây Mượt Mock")

    q = unicodedata.normalize(form, "chuột không dây mượt")
    assert total(client, q=q) == 1


def test_fullwidth_and_halfwidth_queries_find_the_same_product(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Logitech G304 Mock")

    assert [total(client, q=q) for q in ("ＬＯＧＩＴＥＣＨ", "Ｇ３０４", "ｃｈｕｏｔ")] == [1, 1, 1]


# ---------------------------------------------------------------- hãng / mã model
def test_brand_and_model_code_with_accents_match_unaccented_and_uppercase_queries(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Mock mẫu một", brand="Đạt Mock", model_code="Ẩn-Ơ-01")

    assert [total(client, q=q) for q in ("DAT", "đạt", "an-o-01", "AN-Ơ", "Ẩn-Ơ-01")] == [1] * 5


def test_a_term_may_match_the_name_while_another_matches_the_brand(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột gaming Mock", brand="Đạt Mock")
    stock(db_session, "Chuột gaming Mock khác", brand="Other")

    assert names(client, q="dat gaming") == ["Chuột gaming Mock"]


# ---------------------------------------------------------------- kết hợp bộ lọc, phân trang
def test_the_text_filter_combines_with_category_brand_price_and_site(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Mock rẻ", 500_000, category=Category.mouse, brand="Logitech")
    stock(db_session, "Chuột Mock đắt", 3_000_000, category=Category.mouse, brand="Logitech")
    stock(db_session, "Chuột Mock khác", 500_000, category=Category.mouse, brand="Razer")
    stock(db_session, "Bàn phím Mock", 500_000, category=Category.keyboard, brand="Logitech")

    assert names(client, q="chuot", category="mouse", brand="logitech", price_max=1_000_000) == [
        "Chuột Mock rẻ"
    ]
    assert total(client, q="CHUỘT", category="keyboard") == 0
    assert total(client, q="chuot", price_min=2_000_000) == 1
    assert total(client, q="chuot", site="gearvn") == 0


def test_total_counts_every_match_while_a_page_holds_only_page_size(
    client: TestClient, db_session: Session
) -> None:
    for index in range(7):
        stock(db_session, f"Chuột Mock số {index}", 1_000_000 + index)
    stock(db_session, "Bàn phím Mock", 1_000_000)

    page1 = client.get("/api/products", params={"q": "chuot", "page_size": 3, "page": 1}).json()
    page3 = client.get("/api/products", params={"q": "chuot", "page_size": 3, "page": 3}).json()
    page4 = client.get("/api/products", params={"q": "chuot", "page_size": 3, "page": 4}).json()

    assert (page1["total"], len(page1["items"])) == (7, 3)
    assert (page3["total"], len(page3["items"])) == (7, 1)
    assert (page4["total"], len(page4["items"])) == (7, 0)


def test_pages_of_an_accent_insensitive_query_do_not_overlap(
    client: TestClient, db_session: Session
) -> None:
    for index in range(6):
        stock(db_session, f"Chuột Mock số {index}", 1_000_000 + index)

    seen: list[str] = []
    for page in (1, 2, 3):
        seen += names(client, q="chuot", page_size=2, page=page)

    assert sorted(seen) == sorted(f"Chuột Mock số {index}" for index in range(6))


def test_every_term_is_required_and_order_does_not_matter(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Bàn phím cơ không dây Mock")

    assert [
        total(client, q=q) for q in ("khong phim", "phim khong", "phim xanh", "khong khong")
    ] == [
        1,
        1,
        0,
        1,
    ]


def test_a_product_without_a_sellable_offer_is_not_returned_even_when_the_text_matches(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session, canonical_name="Chuột Mock hết hàng")
    add_offer(db_session, product, is_active=False)

    assert total(client, q="chuot") == 0


# ---------------------------------------------------------------- lỗi đã tái hiện
@pytest.mark.parametrize("q", ["ǆ" * 150, "ﷺ" * 12, "㌀" * 60])
def test_a_query_that_expands_under_nfkc_is_handled_not_a_server_error(
    client: TestClient, db_session: Session, q: str
) -> None:
    stock(db_session, "Chuột Mock A")
    assert len(q) <= 200

    response = client.get("/api/products", params={"q": q})

    assert response.status_code in (200, 422), response.text[:200]


def test_a_character_that_unaccent_turns_into_a_backslash_is_not_an_escape(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Mock Tab")

    assert total(client, q="a∖b") == 0


def test_a_character_that_unaccent_turns_into_a_backslash_matches_it_literally(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Mock Tab")
    stock(db_session, r"Chuột Mock a\b")  # tên có dấu gạch chéo ngược thật

    assert names(client, q="a∖b") == [r"Chuột Mock a\b"]


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("mock_a", "Chuột Mock_A"),
        ("mock%a", "Chuột Mock%A"),
        ("môck_a", "Chuột Mock_A"),
        ("môck%a", "Chuột Mock%A"),
    ],
)
def test_like_wildcards_stay_literal_with_and_without_accents_in_the_term(
    client: TestClient, db_session: Session, q: str, expected: str
) -> None:
    stock(db_session, "Chuột Mock_A")
    stock(db_session, "Chuột Mock%A")
    stock(db_session, "Chuột MockXA")

    assert names(client, q=q) == [expected]
