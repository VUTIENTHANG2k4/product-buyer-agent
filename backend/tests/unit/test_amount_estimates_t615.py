"""T6.15 (BUG-T67-4): cách nói ngân sách không bị báo là "giá lệch", giá thật vẫn bị kiểm."""

import pytest

from app.agent.guardrail import Evidence, apply_guardrail
from app.agent.intent import extract_amounts
from app.agent.schemas import FinalAnswer

M = 1_000_000
EVIDENCE = Evidence(product_ids={1}, prices={20 * M, 25 * M})


def skipped(text: str) -> set[int]:
    return extract_amounts(text, skip_estimates=True)


def warnings_for(text: str) -> tuple[int, ...]:
    return apply_guardrail(FinalAnswer(text=text), EVIDENCE).price_warnings


@pytest.mark.parametrize(
    "text",
    [
        "tam gia 30 trieu",
        "TẦM GIÁ 30 TRIỆU",
        "khoảng giá 30tr",
        "ngân sách của tôi là 30 triệu",
        "ngan sach cua ban la 30 trieu",
        "ngân sách của bạn 30 triệu",
        "tối thiểu là 30 triệu",
        "không vượt 30 triệu",
        "không vượt quá 30 triệu",
        "không quá 30 triệu",
        "20tr-25tr",
        "20 triệu – 25 triệu",
        "20 triệu — 25 triệu",
        "20 triệu ~ 25 triệu",
        "1.500.000-2.000.000đ",
        "20-25 triệu",
        "20 đến 25tr",
        "từ 20tr đến 25tr",
    ],
)
def test_budget_phrasings_skip_every_amount(text: str) -> None:
    assert skipped(text) == set()
    assert extract_amounts(text)  # mặc định vẫn đọc ra số tiền


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Logitech G502 đen 1.290.000₫", {1_290_000}),
        ("Corsair K70 đen 3tr", {3 * M}),
        ("Giảm còn 18 triệu", {18 * M}),
        ("Máy A giá là 31 triệu", {31 * M}),
        ("Máy không quá nặng, giá 31 triệu", {31 * M}),
        ("Từ 23 triệu bạn mua được máy này", {23 * M}),
        ("RAM 16 - 31 triệu", {31 * M}),  # gạch có dấu cách sau số trần: có thể là danh sách giá
        ("Máy A 17 triệu - 3 máy còn hàng", {17 * M}),  # sau gạch không phải số tiền
        ("Máy A 31 triệu, của bạn là", {31 * M}),
        ("Máy của bạn là máy 31 triệu", {31 * M}),
        ("i7-13700H giá 31 triệu", {31 * M}),
    ],
)
def test_real_prices_next_to_budget_words_are_still_checked(text: str, expected: set[int]) -> None:
    assert skipped(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tầm giá 30 triệu: máy A giá 31 triệu", (31 * M,)),
        ("Ngân sách của bạn là 30 triệu. Máy A 20 triệu, máy B 31 triệu", (31 * M,)),
        ("Trong khoảng 20-25 triệu có máy A 18 triệu", (18 * M,)),
        ("Từ 20 triệu đến 25 triệu: máy A 25 triệu, máy B 22 triệu", (22 * M,)),
        ("Giá không quá 30 triệu. Máy A 20 triệu", ()),
    ],
)
def test_guardrail_flags_only_the_real_wrong_price(text: str, expected: tuple[int, ...]) -> None:
    assert warnings_for(text) == expected
