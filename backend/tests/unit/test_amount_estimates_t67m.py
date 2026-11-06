"""T6.7m: số tiền đứng sau từ chỉ ngưỡng/ước lượng không bị báo là "lệch giá"."""

import pytest

from app.agent.guardrail import Evidence, apply_guardrail
from app.agent.intent import extract_amounts
from app.agent.schemas import FinalAnswer

EVIDENCE = Evidence(product_ids={1}, prices={20_000_000, 25_990_000})


def warnings_for(text: str) -> tuple[int, ...]:
    return apply_guardrail(FinalAnswer(text=text), EVIDENCE).price_warnings


@pytest.mark.parametrize(
    "text",
    [
        "Máy này dùng cho người có ngân sách trên 50 triệu",
        "Tầm giá dưới 30 triệu có nhiều lựa chọn",
        "Máy B rẻ hơn 2 triệu so với máy A",
        "Khoảng 22 triệu là mức hợp lý",
        "Tầm 20-25 triệu đang có 3 mẫu",
        "Từ 15-18 triệu chủ yếu là máy văn phòng",
        "Bạn tiết kiệm 3 triệu nếu chọn bản RAM 8GB",
        "Chênh lệch 1.500.000 giữa hai máy",
        "Giảm 500k so với tuần trước",
        "Ngân sách tối đa 40 triệu thì nên chọn RTX 4060",
        "Đắt hơn 4 triệu nhưng màn hình tốt hơn",
        "Giá ~ 23 triệu",
        "Đến 28 triệu vẫn còn máy RTX 4070",
    ],
)
def test_thresholds_and_estimates_are_not_price_warnings(text: str) -> None:
    assert warnings_for(text) == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Máy A giá 31.990.000đ", (31_990_000,)),  # giá cụ thể, lệch DB
        ("Giảm còn 18 triệu", (18_000_000,)),  # "giảm còn" là giá mới, không phải mức giảm
        ("Từ 23 triệu bạn mua được máy này", (23_000_000,)),  # "từ" đơn lẻ: vẫn kiểm
        ("Máy A 20 triệu, máy B trên 50 triệu", ()),  # 20 triệu đúng DB, 50 triệu là ngưỡng
        ("Máy A 17 triệu, tiết kiệm 3 triệu", (17_000_000,)),  # chỉ số tiền thứ hai được bỏ qua
    ],
)
def test_real_prices_that_differ_from_the_database_are_still_flagged(
    text: str, expected: tuple[int, ...]
) -> None:
    assert warnings_for(text) == expected


def test_price_matching_the_database_is_never_flagged() -> None:
    assert warnings_for("Máy A giá 25.990.000đ, máy B 20 triệu") == ()


def test_an_amount_written_both_as_estimate_and_as_a_price_is_still_checked() -> None:
    assert warnings_for("Tầm 31 triệu, cụ thể máy C giá 31 triệu") == (31_000_000,)


def test_extract_amounts_keeps_every_amount_by_default() -> None:
    text = "ngân sách trên 50 triệu, máy A 31 triệu"

    assert extract_amounts(text) == {50_000_000, 31_000_000}
    assert extract_amounts(text, skip_estimates=True) == {31_000_000}


def test_estimate_word_far_before_the_amount_does_not_count() -> None:
    assert extract_amounts(
        "Trên thị trường hiện nay, mẫu này được bán với giá 31 triệu", skip_estimates=True
    ) == {31_000_000}


def test_estimate_detection_is_linear_on_huge_input() -> None:
    text = ("trên " * 20_000) + "31 triệu"

    assert extract_amounts(text, skip_estimates=True) == set()
