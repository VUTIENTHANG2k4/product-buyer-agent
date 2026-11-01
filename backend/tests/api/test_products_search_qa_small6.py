"""QA small-fixes-6: `GET /products?q=` sau khi escape được dời ra sau `unaccent` (T7.8).

Biên: ký tự `\\`, `%`, `_` kết hợp chữ có dấu và nhiều từ khóa; mọi ký tự Unicode mà `unaccent`
đổi thành ký tự đặc biệt của LIKE (quét U+0080–U+FFFF trong chính PostgreSQL); mọi ký tự được
`unaccent` đổi tự khớp lại chính nó; `q` dài đúng 200 ký tự; cột hãng/mã model; kết hợp bộ lọc và
phân trang. Test `xfail(strict=True)` mã `BUG-S6-n` là lỗi đã tái hiện.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.db.repositories.products import MAX_TEXT_CHARS, ProductQuery, ProductRepository
from app.domain.enums import Category
from tests.service_support import add_offer, add_product

LIKE_SPECIALS = "%_\\"


def total(client: TestClient, **params: Any) -> int:
    response = client.get("/api/products", params=params)
    assert response.status_code == 200, response.text
    return int(response.json()["total"])


def names(client: TestClient, **params: Any) -> list[str]:
    response = client.get("/api/products", params=params)
    assert response.status_code == 200, response.text
    return sorted(item["name"] for item in response.json()["items"])


def stock(session: Session, name: str, price: int = 1_000_000, **overrides: Any) -> int:
    overrides.setdefault("brand", "ZB")
    product = add_product(session, canonical_name=name, **overrides)
    add_offer(session, product, price=price)
    assert product.id is not None
    return product.id


def repo_names(session: Session, query_text: str, **query: Any) -> list[str]:
    """Tìm thẳng qua repository: không qua chuẩn hóa NFKC của `catalog_service`."""
    page = ProductRepository(session).search(
        ProductQuery.model_validate({"text": query_text, "limit": 100, **query})
    )
    return sorted(hit.product.canonical_name for hit in page.items)


def unaccented(session: Session, value: str) -> str:
    return str(session.execute(text("select unaccent(:v)"), {"v": value}).scalar_one())


def characters_changed_by_unaccent(session: Session) -> list[tuple[str, str]]:
    rows = session.execute(
        text(
            "select chr(i), unaccent(chr(i)) from generate_series(128, 65535) i"
            " where i not between 55296 and 57343 and unaccent(chr(i)) <> chr(i)"
        )
    ).all()
    return [(char, replaced) for char, replaced in rows]


# ---------------------------------------------------------------- 1. \ % _ cùng chữ có dấu
def test_underscore_percent_and_backslash_together_with_an_accented_letter_stay_literal(
    client: TestClient, db_session: Session
) -> None:
    literal = "zqÔ_%\\ Mock"
    stock(db_session, literal)
    for decoy in ("zqOX%\\ Mock", "zqO_X\\ Mock", "zqO_%X Mock", "zqOXX%\\ Mock", "zqO Mock"):
        stock(db_session, decoy)

    assert names(client, q="zqô_%\\") == [literal]
    assert names(client, q="ZQO_%\\") == [literal]


@pytest.mark.parametrize("q", ["zq%", "zq_", "zq\\", "%zq", "_zq", "\\zq", "z%q", "z_q", "z\\q"])
def test_a_single_wildcard_next_to_a_word_matches_only_the_name_that_really_has_it(
    client: TestClient, db_session: Session, q: str
) -> None:
    stock(db_session, "Chuột zq% zq_ zq\\ %zq _zq \\zq z%q z_q z\\q")
    stock(db_session, "Chuột zqXXX zqY XzqY zXq")

    assert names(client, q=q) == ["Chuột zq% zq_ zq\\ %zq _zq \\zq z%q z_q z\\q"]


def test_wildcards_in_several_terms_are_each_literal_and_all_required(
    client: TestClient, db_session: Session
) -> None:
    both = "Chuột zq_1 zq%2 Mock"
    stock(db_session, both)
    stock(db_session, "Chuột zqX1 zqY2 Mock")
    stock(db_session, "Chuột zq_1 zqY2 Mock")
    stock(db_session, "Chuột zqX1 zq%2 Mock")

    assert names(client, q="zq_1 zq%2") == [both]
    assert names(client, q="ZQ%2 chuot zq_1") == [both]


def test_unaccent_turning_a_character_into_a_backslash_before_a_percent_stays_literal(
    client: TestClient, db_session: Session
) -> None:
    literal = "Chuột zqa\\%b"
    stock(db_session, literal)
    for decoy in ("Chuột zqa\\Xb", "Chuột zqaXXb", "Chuột zqa%b", "Chuột zqa\\b"):
        stock(db_session, decoy)

    assert names(client, q="zqa∖%b") == [literal]


def test_unaccent_turning_a_character_into_a_backslash_before_an_underscore_stays_literal(
    client: TestClient, db_session: Session
) -> None:
    literal = "Chuột zqa\\_b"
    stock(db_session, literal)
    for decoy in ("Chuột zqa\\Xb", "Chuột zqaXXb", "Chuột zqa_b", "Chuột zqa\\b"):
        stock(db_session, decoy)

    assert names(client, q="zqa∖_b") == [literal]


def test_a_trailing_backslash_does_not_escape_the_closing_wildcard(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zq\\ Mock")
    stock(db_session, "Chuột zq Mock")

    for q in ("zq\\", "zq∖"):
        assert names(client, q=q) == ["Chuột zq\\ Mock"]


# ---------------------------------------------------------------- 2. ký tự toàn chiều rộng qua NFKC
def test_fullwidth_wildcards_are_literal_after_nfkc(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zqa_b Mock")
    stock(db_session, "Chuột zqa%b Mock")
    stock(db_session, "Chuột zqaXb Mock")

    assert names(client, q="ｚｑａ＿ｂ") == ["Chuột zqa_b Mock"]
    assert names(client, q="ｚｑａ％ｂ") == ["Chuột zqa%b Mock"]


def test_fullwidth_wildcards_stored_in_the_name_match_their_ascii_form_and_not_wildcards(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zqa＿b Mock")
    stock(db_session, "Chuột zqa％b Mock")
    stock(db_session, "Chuột zqaXb Mock")

    assert names(client, q="zqa_b") == ["Chuột zqa＿b Mock"]
    assert names(client, q="zqa%b") == ["Chuột zqa％b Mock"]


# ---------------------------------------------------------------- 3. quét mọi ký tự unaccent đổi
def test_the_scan_finds_the_known_characters_that_unaccent_turns_into_like_specials(
    db_session: Session,
) -> None:
    special = {char for char, replaced in characters_changed_by_unaccent(db_session)
               if any(s in replaced for s in LIKE_SPECIALS)}  # fmt: skip

    assert {"∖", "％", "＿", "＼"} <= special


def test_every_character_that_unaccent_turns_into_a_like_special_is_matched_literally(
    db_session: Session,
) -> None:
    risky = [
        (char, replaced)
        for char, replaced in characters_changed_by_unaccent(db_session)
        if any(special in replaced for special in LIKE_SPECIALS)
    ]
    assert risky
    wrong: list[str] = []
    for index, (char, replaced) in enumerate(risky):
        prefix = f"zq{index:03d}"
        literal = f"{prefix}a{replaced}b Mock"
        decoys = {
            f"{prefix}a{replaced.replace(special, 'X')}b Mock" for special in LIKE_SPECIALS
        } | {f"{prefix}aXXXb Mock", f"{prefix}ab Mock"}
        decoys.discard(literal)
        stock(db_session, literal)
        for decoy in sorted(decoys):
            stock(db_session, decoy)

        found = repo_names(db_session, f"{prefix}a{char}b")
        if found != [literal]:
            wrong.append(f"U+{ord(char):04X} {char!r} -> {replaced!r}: {found}")

    assert wrong == []


def test_every_character_changed_by_unaccent_still_finds_a_name_that_contains_it(
    db_session: Session,
) -> None:
    changed = [
        char
        for char, _ in characters_changed_by_unaccent(db_session)
        if not char.isspace() and char.strip()
    ]
    assert len(changed) > 1000  # đã quét Latin, Hy Lạp, Cyrillic, ký tự toàn chiều rộng…
    words = [f"zq{char}zq" for char in changed]
    stock(db_session, "Mock " + " ".join(words))
    stock(db_session, "Mock zqzq")

    missing: list[str] = []
    chunk: list[str] = []
    for word in [*words, ""]:
        if word and len(" ".join([*chunk, word])) <= MAX_TEXT_CHARS:
            chunk.append(word)
            continue
        if chunk and len(repo_names(db_session, " ".join(chunk))) < 1:
            for single in chunk:
                if "Mock " + " ".join(words) not in repo_names(db_session, single):
                    missing.append(f"U+{ord(single[2]):04X}")
        chunk = [word] if word else []

    assert missing == []


def test_a_term_made_only_of_marks_that_unaccent_deletes_does_not_hide_the_other_terms(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zq Mock")
    stock(db_session, "Bàn phím Mock")

    assert names(client, q="́ chuot") == ["Chuột zq Mock"]
    assert names(client, q="chuot ̣̂") == ["Chuột zq Mock"]


@pytest.mark.parametrize("q", ["chội", "chội", "chội", "chội"])
def test_combining_marks_in_any_order_find_the_composed_name(
    client: TestClient, db_session: Session, q: str
) -> None:
    stock(db_session, "Chộiz Mock")

    assert names(client, q=q + "z") == ["Chộiz Mock"]


def test_a_fraction_character_is_found_by_its_ascii_expansion_through_the_repository(
    db_session: Session,
) -> None:
    stock(db_session, "Mock zq½")
    stock(db_session, "Mock zq 1/2")

    # unaccent("½") = " 1/2" (có khoảng trắng đầu): cả hai tên chứa "1/2" nên cùng khớp.
    assert repo_names(db_session, "½") == ["Mock zq 1/2", "Mock zq½"]
    assert unaccented(db_session, "½") == " 1/2"


# ---------------------------------------------------------------- 4. độ dài 200
@pytest.mark.parametrize("char", ["_", "%", "\\", "ô", "∖"])
def test_a_query_of_exactly_two_hundred_wildcards_is_literal_and_matches_only_that_run(
    client: TestClient, db_session: Session, char: str
) -> None:
    base = "\\" if char == "∖" else char
    base = "o" if char == "ô" else base
    stock(db_session, "Chuột zq" + base * 200)
    stock(db_session, "Chuột zq" + "X" * 200)
    stock(db_session, "Chuột zq" + base * 199)

    assert len(char * 200) == 200
    assert names(client, q=char * 200) == ["Chuột zq" + base * 200]


def test_a_two_hundred_character_multi_term_query_with_accents_matches(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột không dây Mock")
    q = " ".join(["chuột"] * 32)  # 32 x 5 chữ + 31 dấu cách = 191 ký tự
    assert len(q) == 191

    assert total(client, q=q) == 1
    assert total(client, q=q + " zzzzzzzz") == 0  # đúng 200 ký tự


def test_a_query_of_two_hundred_backslash_and_wildcard_terms_returns_without_a_server_error(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột Mock")
    q = " ".join(["\\%_"] * 50)

    response = client.get("/api/products", params={"q": q[:200]})

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0


# ---------------------------------------------------------------- 5. cột hãng và mã model
def test_wildcards_are_literal_in_the_brand_and_model_code_columns_too(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zq1 Mock", brand="Ab_Cd", model_code="MC%1")
    stock(db_session, "Chuột zq2 Mock", brand="AbXCd", model_code="MCX1")
    stock(db_session, "Chuột zq3 Mock", brand="Ab\\Cd", model_code="MC\\1")

    assert names(client, q="ab_cd") == ["Chuột zq1 Mock"]
    assert names(client, q="mc%1") == ["Chuột zq1 Mock"]
    assert names(client, q="AB\\CD") == ["Chuột zq3 Mock"]
    assert names(client, q="mc\\1") == ["Chuột zq3 Mock"]


def test_an_accented_brand_with_a_wildcard_matches_the_unaccented_query(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zq1 Mock", brand="Đạt_Mock")
    stock(db_session, "Chuột zq2 Mock", brand="ĐạtXMock")

    assert names(client, q="dat_mock") == ["Chuột zq1 Mock"]
    assert names(client, q="ĐẠT_MOCK") == ["Chuột zq1 Mock"]


def test_a_null_model_code_never_breaks_a_text_search(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zq_ Mock", model_code=None)

    assert names(client, q="zq_") == ["Chuột zq_ Mock"]
    assert total(client, q="zqx") == 0


# ---------------------------------------------------------------- 6. bộ lọc và phân trang
def test_a_wildcard_query_combines_with_filters_and_never_widens_the_result(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zq_a rẻ", 500_000, category=Category.mouse, brand="Logitech")
    stock(db_session, "Chuột zq_a đắt", 3_000_000, category=Category.mouse, brand="Logitech")
    stock(db_session, "Chuột zqXa rẻ", 500_000, category=Category.mouse, brand="Logitech")
    stock(db_session, "Bàn phím zq_a", 500_000, category=Category.keyboard, brand="Logitech")

    assert names(client, q="zq_a", category="mouse", price_max=1_000_000) == ["Chuột zq_a rẻ"]
    assert names(client, q="ZQ_A", brand="logitech", category="keyboard") == ["Bàn phím zq_a"]
    assert total(client, q="zq_a", category="mouse", price_min=4_000_000) == 0
    assert total(client, q="zq%a") == 0
    assert total(client, q="zq_a", site="gearvn") == 0


def test_pages_of_a_wildcard_query_are_disjoint_and_total_counts_only_literal_matches(
    client: TestClient, db_session: Session
) -> None:
    for index in range(7):
        stock(db_session, f"Chuột zq_{index} Mock", 1_000_000 + index)
    for index in range(5):
        stock(db_session, f"Chuột zqX{index} Mock", 1_000_000 + index)

    seen: list[str] = []
    for page in (1, 2, 3, 4):
        response = client.get("/api/products", params={"q": "zq_", "page_size": 3, "page": page})
        body = response.json()
        assert body["total"] == 7
        seen += [item["name"] for item in body["items"]]

    assert sorted(seen) == sorted(f"Chuột zq_{index} Mock" for index in range(7))


def test_a_query_that_unaccent_empties_applies_no_filter_but_keeps_pagination_correct(
    client: TestClient, db_session: Session
) -> None:
    for index in range(4):
        stock(db_session, f"Chuột zq{index} Mock", 1_000_000 + index)

    body = client.get("/api/products", params={"q": "́", "page_size": 3}).json()

    assert (body["total"], len(body["items"])) == (4, 3)


def test_a_stored_name_with_a_character_that_unaccent_turns_into_a_backslash_matches_both_forms(
    client: TestClient, db_session: Session
) -> None:
    stock(db_session, "Chuột zqa∖b Mock")
    stock(db_session, "Chuột zqaXb Mock")

    assert names(client, q="zqa∖b") == ["Chuột zqa∖b Mock"]
    assert names(client, q="zqa" + chr(92) + "b") == ["Chuột zqa∖b Mock"]
    assert names(client, q="zqa＼b") == ["Chuột zqa∖b Mock"]
