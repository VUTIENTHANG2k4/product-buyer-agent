"""QA T6.7v: `contains`/`contains_any` ở các ca biên (chuỗi rỗng, ký tự LIKE, Unicode, kiểu trường).

Chạy trên PostgreSQL thật qua `ProductRepository.search`; không đoán kết quả SQL bằng chuỗi.
"""

import unicodedata
from typing import Any

import pytest
from sqlmodel import Session

from app.db.models import Product
from app.db.repositories import ProductQuery, ProductRepository
from app.domain.dto import MAX_FILTER_TEXT, SpecFilter
from app.domain.enums import Category
from tests.factories import make_offer, make_product


def add(session: Session, category: Category = Category.laptop, **specs: Any) -> Product:
    product = make_product(category=category, specs=specs)
    session.add(product)
    session.flush()
    session.add(make_offer(product.id or 0))
    session.flush()
    return product


def found(
    session: Session, spec_filter: SpecFilter, category: Category = Category.laptop
) -> set[int]:
    query = ProductQuery(category=category, spec_filters=[spec_filter])
    return {hit.product.id or 0 for hit in ProductRepository(session).search(query).items}


def contains(field: str, value: Any) -> SpecFilter:
    return SpecFilter(field=field, op="contains", value=value)


def contains_any(field: str, values: list[str]) -> SpecFilter:
    return SpecFilter(field=field, op="contains_any", value=values)


# ---- chuỗi rỗng -------------------------------------------------------------------------------
def test_empty_string_never_matches_products_that_lack_a_string_value(db_session: Session) -> None:
    add(db_session)  # không có cpu_model
    add(db_session, cpu_model=None)
    add(db_session, cpu_model=["i7"])  # kiểu danh sách
    add(db_session, cpu_model=16)  # kiểu số
    add(db_session, cpu_model=True)  # kiểu bool

    assert found(db_session, contains("cpu_model", "")) == set()


def test_contains_any_with_an_empty_list_matches_nothing(db_session: Session) -> None:
    add(db_session, cpu_model="i7-14700HX")

    assert found(db_session, contains_any("cpu_model", [])) == set()


def test_contains_any_with_only_an_empty_string_matches_nothing_on_missing_fields(
    db_session: Session,
) -> None:
    add(db_session)

    assert found(db_session, contains_any("cpu_model", [""])) == set()


# ---- ký tự đặc biệt của LIKE / escape ---------------------------------------------------------
@pytest.mark.parametrize(
    "stored", ["i7_%x", "100%", "a_b", "back\\slash", "a/b", "a//b", "50%_off"]
)
def test_special_characters_match_themselves_literally(db_session: Session, stored: str) -> None:
    target = add(db_session, cpu_model=stored)
    add(db_session, cpu_model="i7-14700HX")  # không được khớp nhầm do ký tự đại diện

    assert found(db_session, contains("cpu_model", stored)) == {target.id}


@pytest.mark.parametrize(
    ("stored", "needle"),
    [("a/b", "a//b"), ("a//b", "a/b"), ("ab", "a_"), ("ab", "%b"), ("ab", "a\\"), ("a_b", "a%b")],
)
def test_escape_character_in_value_does_not_turn_into_a_wildcard(
    db_session: Session, stored: str, needle: str
) -> None:
    product = add(db_session, cpu_model=stored)
    expected = {product.id} if needle in stored else set()

    assert found(db_session, contains("cpu_model", needle)) == expected


def test_contains_any_treats_each_value_literally(db_session: Session) -> None:
    percent = add(db_session, cpu_model="50% off")
    add(db_session, cpu_model="i7-14700HX")

    assert found(db_session, contains_any("cpu_model", ["%", "zzz"])) == {percent.id}


# ---- Unicode / tiếng Việt ---------------------------------------------------------------------
def test_vietnamese_substring_matches_regardless_of_case(db_session: Session) -> None:
    red = add(db_session, Category.keyboard, switch_name="Kailh Box Đỏ")
    add(db_session, Category.keyboard, switch_name="Gateron Brown")

    for needle in ("đỏ", "ĐỎ", "Đỏ", "box đỏ"):
        assert found(db_session, contains("switch_name", needle), Category.keyboard) == {red.id}


def test_vietnamese_needle_without_accents_does_not_match_accented_text(
    db_session: Session,
) -> None:
    add(db_session, Category.keyboard, switch_name="Kailh Box Đỏ")

    assert found(db_session, contains("switch_name", "do"), Category.keyboard) == set()
    assert found(db_session, contains("switch_name", "Tam"), Category.keyboard) == set()


def test_accented_word_inside_a_longer_title_matches(db_session: Session) -> None:
    mid = add(db_session, cpu_model="Tầm trung Core i5")

    assert found(db_session, contains("cpu_model", "Tầm")) == {mid.id}
    assert found(db_session, contains("cpu_model", "tầm TRUNG")) == {mid.id}


def test_decomposed_unicode_needle_matches_the_composed_stored_text(db_session: Session) -> None:
    target = add(db_session, Category.keyboard, switch_name="Kailh Box Đỏ")
    needle = unicodedata.normalize("NFD", "Box Đỏ")
    assert needle != "Box Đỏ"

    assert found(db_session, contains("switch_name", needle), Category.keyboard) == {target.id}


def test_emoji_and_cjk_needles_are_just_text(db_session: Session) -> None:
    add(db_session, cpu_model="i7")

    assert found(db_session, contains("cpu_model", "💥")) == set()
    assert found(db_session, contains("cpu_model", "日本語")) == set()


# ---- giá trị dài / tên trường lạ --------------------------------------------------------------
def test_value_at_the_dto_length_limit_runs_without_error(db_session: Session) -> None:
    add(db_session, cpu_model="i7")

    assert found(db_session, contains("cpu_model", "x" * MAX_FILTER_TEXT)) == set()


def test_very_long_stored_text_is_searched_by_substring(db_session: Session) -> None:
    target = add(db_session, cpu_model="a" * 100_000 + "i7")

    assert found(db_session, contains("cpu_model", "i7")) == {target.id}


@pytest.mark.parametrize(
    "field", ["does_not_exist", "cpu'model", 'cpu"model', "cpu_model; DROP TABLE product", "é"]
)
def test_unknown_or_hostile_field_names_match_nothing_and_do_not_raise(
    db_session: Session, field: str
) -> None:
    add(db_session, cpu_model="i7")

    assert found(db_session, contains(field, "i7")) == set()
    assert found(db_session, contains_any(field, ["i7"])) == set()


# ---- kiểu của trường: list / chuỗi / số / bool / null -----------------------------------------
def test_list_field_requires_an_exact_element_not_a_substring(db_session: Session) -> None:
    wired = add(db_session, Category.mouse, connection=["wired", "wireless_2_4"])

    assert found(db_session, contains("connection", "wired"), Category.mouse) == {wired.id}
    assert found(db_session, contains("connection", "wire"), Category.mouse) == set()
    assert found(db_session, contains("connection", "WIRED"), Category.mouse) == set()


def test_string_field_with_exact_value_matches_and_is_case_insensitive(db_session: Session) -> None:
    mech = add(db_session, Category.keyboard, switch_type="mechanical")

    assert found(db_session, contains("switch_type", "mechanical"), Category.keyboard) == {mech.id}
    assert found(db_session, contains("switch_type", "MECH"), Category.keyboard) == {mech.id}


def test_number_and_bool_fields_never_match_a_string_needle(db_session: Session) -> None:
    add(db_session, ram_gb=16, is_gaming=True)

    assert found(db_session, contains("ram_gb", "16")) == set()
    assert found(db_session, contains("ram_gb", "1")) == set()
    assert found(db_session, contains("is_gaming", "true")) == set()
    assert found(db_session, contains_any("is_gaming", ["t", "true"])) == set()


def test_bool_and_int_needles_use_list_membership_only(db_session: Session) -> None:
    flags = add(db_session, flags=[True, False], nums=[1, 2])

    assert found(db_session, contains("flags", True)) == {flags.id}
    assert found(db_session, contains("nums", 2)) == {flags.id}
    assert found(db_session, contains("nums", 3)) == set()


def test_json_null_and_empty_list_never_match(db_session: Session) -> None:
    add(db_session, cpu_model=None, connection=[])

    assert found(db_session, contains("cpu_model", "null")) == set()
    assert found(db_session, contains("connection", "wired")) == set()


def test_nested_object_field_does_not_match_a_string_needle(db_session: Session) -> None:
    add(db_session, cpu_model={"name": "i7"})

    assert found(db_session, contains("cpu_model", "i7")) == set()
    assert found(db_session, contains("cpu_model", "name")) == set()


def test_negative_and_float_needles_do_not_raise(db_session: Session) -> None:
    add(db_session, weights=[1.5, -2])

    assert found(db_session, contains("weights", -2)) != set()
    assert found(db_session, contains("weights", 1.5)) != set()


def test_contains_any_mixes_exact_list_members_and_substrings_across_products(
    db_session: Session,
) -> None:
    mouse = add(db_session, Category.mouse, connection=["bluetooth"], model_name="Pro X")
    other = add(db_session, Category.mouse, connection=["wired"], model_name="Viper Mini")

    got = found(db_session, contains_any("connection", ["bluetooth", "wired"]), Category.mouse)
    assert got == {mouse.id, other.id}
    assert found(db_session, contains_any("model_name", ["pro", "mini"]), Category.mouse) == {
        mouse.id,
        other.id,
    }
