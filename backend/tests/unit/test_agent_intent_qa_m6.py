"""QA M6: biên và hồi quy cho extract_amounts / postprocess_intent / planner (không DB)."""

import unicodedata
from typing import Any, Literal

import pytest

from app.agent.intent import MAX_AMOUNT_VND, extract_amounts, postprocess_intent
from app.agent.planner import Planner
from app.agent.testing import ScriptedChatModel
from app.domain.dto import QueryIntent, SpecFilter


def intent(**fields: object) -> QueryIntent:
    return QueryIntent.model_validate({"plan_steps": ["Tìm trong danh mục"], **fields})


# ---- số khổng lồ không được làm hỏng cả lượt (BUG-M6-1) ----
@pytest.mark.parametrize(
    "message",
    [
        "1" * 310 + "tr",  # float(...) = inf → OverflowError trước khi sửa
        "1" * 400 + "k",
        "1" * 4301,  # vượt giới hạn 4300 chữ số của int(str)
        "1" + ".000" * 2000,
        "99999999999999999999 triệu",
        "999999999 triệu",  # 9,99e14 VND: vượt trần
    ],
)
def test_absurdly_large_numbers_are_ignored_not_raised(message: str) -> None:
    assert extract_amounts(message) == set()


def test_huge_number_in_the_user_message_does_not_break_postprocess() -> None:
    result = postprocess_intent(intent(category="laptop", price_max=30), "1" * 310 + "tr")
    assert result.price_max == 30  # không có số tiền hợp lệ để đối chiếu: giữ nguyên


async def test_planner_survives_a_message_that_used_to_overflow() -> None:
    model = ScriptedChatModel(script=[{"category": "laptop", "plan_steps": ["Tìm laptop"]}])
    result = await Planner(model).plan("laptop " + "9" * 400 + "tr")
    assert result.category is not None and result.category.value == "laptop"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("9.999", set()),
        ("10.000", {10_000}),
        ("9k", set()),
        ("10k", {10_000}),
        ("1.000.000.000.000", {MAX_AMOUNT_VND}),
        ("1.000.000.000.001", set()),
        ("0", set()),
        ("00030 triệu", {30_000_000}),
    ],
)
def test_amount_boundaries(message: str, expected: set[int]) -> None:
    assert extract_amounts(message) == expected


# ---- chuỗi Unicode ----
@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_amounts_do_not_depend_on_the_unicode_normal_form(
    form: Literal["NFC", "NFD", "NFKC", "NFKD"],
) -> None:
    message = unicodedata.normalize(form, "laptop dưới 30 triệu hoặc 25 triệu đồng")
    assert extract_amounts(message) == {30_000_000, 25_000_000}


def test_fullwidth_digits_and_unaccented_text_still_count() -> None:
    assert extract_amounts("laptop duoi ３０ trieu") == {30_000_000}


# ---- đơn vị đo không phải tiền (BUG-M6-6) ----
@pytest.mark.parametrize(
    "message",
    [
        "chuột 16.000 dpi",
        "chuột 25.600 DPI",
        "chuột 26k dpi",
        "điện thoại pin 5.000 mAh",
        "màn hình 1.000 nits",
        "laptop màn 144 hz 20.000 hz",
    ],
)
def test_measurement_units_after_a_number_are_not_money(message: str) -> None:
    assert extract_amounts(message) == set()


def test_dpi_does_not_stop_the_approximate_price_rule() -> None:
    result = postprocess_intent(intent(category="mouse"), "chuột 16.000 dpi tầm 500k")
    assert (result.price_min, result.price_max) == (450_000, 550_000)


def test_a_price_next_to_a_measurement_is_still_found() -> None:
    assert extract_amounts("pin 5000 mah giá dưới 10.000.000") == {10_000_000}


# ---- thiếu sót ghi nhận (xfail) ----
@pytest.mark.xfail(
    strict=True,
    reason="BUG-M6-11: 'RTX 4060 trở xuống' bị đổi thành gpu_rank >= hạng(RTX 4060) (ngược chiều)",
)
@pytest.mark.parametrize(
    "message", ["laptop gaming RTX 4060 trở xuống", "laptop card rtx 4070 tối đa"]
)
def test_gpu_upper_bound_wording_does_not_become_a_lower_bound(message: str) -> None:
    result = postprocess_intent(intent(category="laptop"), message)
    assert not any(spec.op == "gte" and spec.field == "gpu_rank" for spec in result.spec_filters)


@pytest.mark.xfail(
    strict=True,
    reason="BUG-M6-12: số tiền viết cách nghìn bằng dấu cách ('27 990 000') không được nhận ra",
)
def test_space_grouped_thousands_are_read_as_money() -> None:
    assert extract_amounts("laptop dưới 30 000 000 đồng") == {30_000_000}


# ---- tính chất ----
@pytest.mark.parametrize(
    "message",
    [
        "",
        "   ",
        "laptop",
        "laptop tầm 20 triệu rtx 4060 trở lên ram 16gb ssd 1tb",
        "chuột dưới 500k trên gearvn và shopee",
        "tai nghe " * 120,
    ],
)
def test_postprocess_always_returns_a_valid_intent(message: str) -> None:
    raw: dict[str, Any] = {"category": "laptop", "price_max": 20, "plan_steps": ["a"] * 9}
    result = postprocess_intent(intent(**raw), message)
    assert QueryIntent.model_validate(result.model_dump()) == result
    assert 1 <= len(result.plan_steps) <= 5


def test_zero_prices_are_not_treated_as_a_missing_unit() -> None:
    result = postprocess_intent(intent(category="laptop", price_min=0), "laptop dưới 30 triệu")
    assert result.price_min == 0


def test_bool_spec_filter_values_survive_postprocess() -> None:
    flag = SpecFilter(field="is_gaming", op="eq", value=True)
    result = postprocess_intent(intent(category="laptop", spec_filters=[flag]), "laptop gaming")
    assert result.spec_filters == [flag]
