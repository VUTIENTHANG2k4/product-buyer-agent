"""QA small-1: `extract_amounts` (số cách nghìn bằng dấu cách) và chiều cận GPU của `intent.py`.

Test `xfail(strict=True)` là lỗi đã tái hiện (mã BUG-S1-n); khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import time

import pytest

from app.agent.intent import _gpu_is_upper_bound, extract_amounts, postprocess_intent
from app.domain.dto import QueryIntent
from app.normalize.text import fold


def bug(code: str, why: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{code}: {why}")


def laptop_intent() -> QueryIntent:
    return QueryIntent.model_validate({"plan_steps": ["Tìm laptop"], "category": "laptop"})


def gpu_ops(message: str) -> list[tuple[str, int | str | float | bool | list[str]]]:
    result = postprocess_intent(laptop_intent(), message)
    return [(s.op, s.value) for s in result.spec_filters if s.field == "gpu_rank"]


# ---- số tiền cách nghìn bằng dấu cách ----
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("27 990 000", {27_990_000}),
        ("27 990 000 đ", {27_990_000}),
        ("27 990 000đ", {27_990_000}),
        ("1 000 000 đ", {1_000_000}),
        ("1 000 000", {1_000_000}),
        ("30 000 000 vnd", {30_000_000}),
        ("30 000 000d", {30_000_000}),
        ("laptop 27 990 000 hoặc 30 000 000", {27_990_000, 30_000_000}),
        ("giá 27 990 000-30 000 000", {27_990_000, 30_000_000}),
        ("27 990 000 - 30 000 000", {27_990_000, 30_000_000}),
        ("27 990 000 000", {27_990_000_000}),
        ("30 000 000", {30_000_000}),
        ("30 000 000", {30_000_000}),
        ("2 500 000 k", {2_500_000_000}),
    ],
)
def test_space_grouped_amounts_in_more_shapes(message: str, expected: set[int]) -> None:
    assert extract_amounts(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "laptop 16 GB 512 GB",
        "16 GB 512 GB 1 TB",
        "ram 16 512",
        "laptop RAM 16 SSD 512 1 000",
        "1 000",
        "12 345",
        "30 000 000 dpi",
        "30 000 000 mah",
        "ssd 1 000 000 gb",
        "144 240 360 Hz",
        "1 2 3 4 5 6 7",
        "30 0000 00",
        "30 000 00",
        "i7 13700 000",
        "27 990 000 000 000 000",
        "999 999 999 999 999",
        "5 000 000 000 000",
        "liên hệ 0901 234 567",
        "liên hệ 090 123 4567",
    ],
)
def test_space_separated_numbers_that_are_not_money_are_ignored(message: str) -> None:
    assert extract_amounts(message) == set()


def test_a_space_grouped_price_drives_the_money_scale_fix_and_the_range() -> None:
    result = postprocess_intent(
        QueryIntent.model_validate(
            {"plan_steps": ["x"], "category": "laptop", "price_max": 30, "price_min": 20}
        ),
        "laptop từ 20 000 000 đến 30 000 000 đồng",
    )

    assert (result.price_min, result.price_max) == (20_000_000, 30_000_000)


# ---- chiều cận GPU ----
@pytest.mark.parametrize(
    "message",
    [
        "laptop RTX 4060 trở lên dưới 30 triệu",
        "laptop RTX 4060 trở lên",
        "laptop RTX 4060",
        "laptop tối đa 30 triệu, RTX 4060",
        "laptop tối đa 30 triệu RTX 4060",
        "laptop giá tối đa 30 triệu card RTX 4060",
        "laptop RTX 4060 giá không quá 30 triệu",
        "laptop RTX 4060 nhỏ hơn 2kg",
        "laptop RTX 4060 tối đa 2kg",
        "laptop tối đa 2kg RTX 4060",
        "laptop RTX 4060 tối đa 16gb",
        "laptop mạnh hơn RTX 4060",
        "laptop RTX 4060 trở lên, giá 30 triệu trở xuống",
        "laptop giá từ 20 triệu trở xuống, card RTX 4060 trở lên",
        "laptop ngân sách 20 triệu trở xuống, RTX 4060",
    ],
)
def test_price_and_weight_limits_do_not_flip_the_gpu_bound(message: str) -> None:
    assert gpu_ops(message) == [("gte", 40)]


@pytest.mark.parametrize(
    "message",
    [
        "laptop tối đa 30 triệu RTX 4060 trở xuống",
        "laptop RTX 4060 trở xuống dưới 30 triệu",
        "laptop RTX 4060 trở xuống tối đa 30 triệu",
        "laptop RTX 4060 trở xuống, giá 30 triệu trở xuống",
        "laptop tối đa RTX 4060 giá 30 triệu",
        "laptop RTX 4060 tối đa",
        "laptop RTX 4060 tro xuong",
        "laptop RTX 4060 TRỞ XUỐNG",
        "laptop RTX4060 trở xuống",
        "laptop RTX 4060 trở xuống 16GB ram",
    ],
)
def test_real_upper_bound_wording_becomes_lte(message: str) -> None:
    assert gpu_ops(message) == [("lte", 40)]


@pytest.mark.parametrize(
    "message",
    [
        "laptop RTX 4060 hoặc RTX 4070 trở xuống",
        "laptop RTX 4070 trở lên hoặc RTX 4050 trở xuống",
        "laptop RTX 4060 trở lên, RTX 3050 trở xuống",
    ],
)
def test_two_cards_in_one_message_never_produce_a_guessed_gpu_filter(message: str) -> None:
    assert gpu_ops(message) == []


def test_upper_bound_detection_is_pure_and_total_on_odd_text() -> None:
    for text in ["", " ", "rtx", "rtx 4060", "tro xuong", "toi da rtx", "\x00rtx 4060 tro xuong"]:
        assert isinstance(_gpu_is_upper_bound(fold(text)), bool)


@pytest.mark.parametrize(
    "message",
    [
        "laptop RTX 4060 giá tối đa là 30 triệu",
        "laptop RTX 4060 ngân sách tối đa khoảng 30 triệu",
        "laptop RTX 4060 tối đa chỉ 30 triệu",
        "laptop RTX 4060 không quá nặng",
    ],
)
def test_a_price_cap_with_a_filler_word_before_the_number_keeps_gte(message: str) -> None:
    assert gpu_ops(message) == [("gte", 40)]


@pytest.mark.parametrize(
    "message",
    [
        "laptop giá 20 triệu trở xuống card RTX 4060 trở lên",
        "laptop 20 triệu trở xuống RTX 4060 trở lên",
        "laptop giá 20 triệu trở xuống RTX 4060",
        "laptop dưới 30 triệu trở xuống RTX 4060",
    ],
)
def test_a_price_trở_xuống_right_before_the_card_name_does_not_flip_it(message: str) -> None:
    assert gpu_ops(message) == [("gte", 40)]


# ---- ngăn ReDoS: thời gian tuyến tính trên đầu vào lớn ----
@pytest.mark.parametrize(
    "payload",
    [
        "1 000 " * 100_000,
        "123 " * 150_000,
        "0 " * 250_000,
        "99 999 " * 80_000,
        "1" * 500_000,
        "1.000" * 100_000,
        " " * 500_000,
        "rtx " * 150_000,
        "rtx 4060 " * 50_000,
        "tối đa " * 100_000,
        "rtx 4060 tối đa " * 40_000,
        "rtx" + " " * 500_000 + "4060",
        "tối đa" + " " * 500_000 + "rtx 4060",
    ],
    ids=[
        "space-groups",
        "triples",
        "zeros",
        "mixed",
        "digits",
        "dots",
        "spaces",
        "rtx",
        "rtx-4060",
        "toi-da",
        "rtx-toi-da",
        "rtx-space",
        "toi-da-space",
    ],
)
def test_amount_and_gpu_parsing_stay_linear_on_half_megabyte_inputs(payload: str) -> None:
    started = time.perf_counter()

    extract_amounts(payload)
    postprocess_intent(laptop_intent(), payload)

    assert time.perf_counter() - started < 10
