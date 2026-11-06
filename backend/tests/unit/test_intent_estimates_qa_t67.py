"""QA T6.7m: `extract_amounts(skip_estimates=True)` / `_is_estimate` ở các ca biên.

Hai nhóm: (1) từ chỉ ngưỡng tiếng Việt (có dấu/không dấu/viết hoa), cách xa số, màu "đen" và
"đến"; (2) thời gian tuyến tính (đo tốc độ tăng khi đầu vào ×4, không dùng ngưỡng giây: T6.14).
"""

import time
from collections.abc import Callable

import pytest

from app.agent.guardrail import Evidence, apply_guardrail
from app.agent.intent import extract_amounts
from app.agent.schemas import FinalAnswer

M = 1_000_000


def skipped(text: str) -> set[int]:
    return extract_amounts(text, skip_estimates=True)


# ---- chính tả / hoa thường / không dấu --------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "dưới 30 triệu",
        "DƯỚI 30 TRIỆU",
        "Dưới 30 Triệu",
        "duoi 30 trieu",
        "DUOI 30 TRIEU",
        "trên 30tr",
        "tren 30tr",
        "TRÊN 30TR",
        "Tầm 30 triệu",
        "tam 30 trieu",
        "khoảng 30 triệu",
        "KHOANG 30 TRIEU",
        "khoảng\n30 triệu",
        "dưới\t30 triệu",
        "dưới   30 triệu",
        "~30tr",
        "≈ 30tr",
        "< 30tr",
        "> 30tr",
        "tối đa 30 triệu",
        "tối thiểu 30 triệu",
        "ngân sách 30 triệu",
        "xấp xỉ 30 triệu",
        "tiết kiệm 30 triệu",
        "chênh lệch 30 triệu",
        "rẻ hơn 30 triệu",
        "đắt hơn 30 triệu",
        "gần 30 triệu",
        "giảm 30 triệu",
    ],
)
def test_threshold_words_in_any_case_or_without_accents_skip_the_amount(text: str) -> None:
    assert skipped(text) == set()
    assert extract_amounts(text) == {30 * M}  # mặc định vẫn đọc đủ


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("dưới 500k", 500_000),
        ("dưới 1,5tr", 1_500_000),
        ("dưới 2m", 2 * M),
        ("dưới 30.000.000đ", 30 * M),
        ("dưới 1.500.000 VND", 1_500_000),
        ("trên 2tr5", 2_500_000),
    ],
)
def test_units_k_tr_m_and_plain_numbers_are_skipped_after_a_threshold_word(
    text: str, amount: int
) -> None:
    assert extract_amounts(text) == {amount}
    assert skipped(text) == set()


def test_each_amount_is_judged_by_its_own_lead_not_by_the_first_threshold_word() -> None:
    assert skipped("dưới 30tr, 25tr, 20tr") == {25 * M, 20 * M}


def test_threshold_word_just_outside_the_lead_window_does_not_count() -> None:
    far = "dưới " + "x" * 41 + " 30 triệu"

    assert skipped(far) == {30 * M}


def test_threshold_word_at_the_edge_of_the_lead_window_still_counts() -> None:
    near = "dưới " + " " * 5 + "30 triệu"

    assert skipped(near) == set()


@pytest.mark.parametrize("text", ["", "   ", "dưới", "30", "triệu", "dưới triệu", "~", "≈≈≈"])
def test_degenerate_strings_return_nothing_and_do_not_raise(text: str) -> None:
    assert skipped(text) == set()


# ---- "đen" (màu) và "đến" ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["Chuột đen 450k", "Chuột màu đen: 450k", "Bàn phím đen, 450k", "Tai nghe ĐEN 450k"],
)
def test_colour_black_before_a_price_does_not_hide_the_price(text: str) -> None:
    assert skipped(text) == {450_000}


@pytest.mark.parametrize(
    "text",
    ["Logitech G502 đen 1.290.000₫", "Chuột G304 đen 790k", "Corsair K70 đen 3tr"],
)
def test_model_code_ending_in_digits_followed_by_the_colour_black_keeps_its_price(
    text: str,
) -> None:
    assert len(skipped(text)) == 1


@pytest.mark.parametrize("text", ["từ 20 đến 25 triệu", "Từ 20 đến 28 triệu vẫn còn máy"])
def test_a_range_written_with_den_skips_its_upper_end(text: str) -> None:
    assert skipped(text) == set()


# ---- khoảng giá ghi bằng gạch / có đơn vị ở cả hai đầu ----------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Trong tầm giá 30 triệu có 3 máy",
        "Trong khoảng giá 30 triệu",
        "Ngân sách của bạn là 30 triệu",
        "Giá 20-25 triệu",
        "Mức giá 20-25tr",
        "Từ 20 triệu đến 25 triệu",
        "20 triệu - 25 triệu",
        "tối đa là 30 triệu",
        "không quá 30 triệu",
    ],
)
def test_common_budget_phrasings_are_not_price_mismatches(text: str) -> None:
    assert skipped(text) == set()


# ---- guardrail --------------------------------------------------------------------------------
EVIDENCE = Evidence(product_ids={1}, prices={20 * M})


def test_guardrail_flags_a_real_wrong_price_even_with_threshold_talk_around_it() -> None:
    verdict = apply_guardrail(
        FinalAnswer(text="Ngân sách tối đa 40 triệu. Máy A giá 31 triệu, máy B giá 20 triệu."),
        EVIDENCE,
    )

    assert verdict.price_warnings == (31 * M,)


def test_guardrail_flags_price_near_a_threshold_in_the_other_clause() -> None:
    verdict = apply_guardrail(FinalAnswer(text="Dưới 40 triệu: máy A 31 triệu"), EVIDENCE)

    assert verdict.price_warnings == (31 * M,)


# ---- thời gian tuyến tính ---------------------------------------------------------------------
def growth(make: Callable[[int], str], small: int = 50_000) -> float:
    """Tỉ lệ thời gian khi đầu vào ×4 (lấy lần chạy nhanh nhất để giảm nhiễu)."""

    def best(size: int) -> float:
        text = make(size)
        runs = []
        for _ in range(3):
            start = time.perf_counter()
            skipped(text)
            runs.append(time.perf_counter() - start)
        return min(runs)

    return best(small * 4) / max(best(small), 1e-6)


SHAPES: dict[str, Callable[[int], str]] = {
    "threshold_words": lambda n: ("trên " * n)[:n] + "31 triệu",
    "spaces_then_amount": lambda n: " " * n + "30 triệu",
    "letters_then_amount": lambda n: "a" * n + "30 triệu",
    "digits_only": lambda n: "9" * n,
    "digits_then_unit": lambda n: "9" * n + "tr",
    "zero_space_pairs": lambda n: "0 " * (n // 2) + "31 triệu",
    "thousand_groups": lambda n: "1 111 " * (n // 6),
    "dot_groups": lambda n: "1.111" * (n // 5) + "đ",
    "ranges": lambda n: "20-" * (n // 3) + "25tr",
    "many_amounts": lambda n: "dưới 30tr, " * (n // 11),
    "tilde_marks": lambda n: "~" * n + "30tr",
    "den_chain": lambda n: "1 đen " * (n // 6) + "2tr",
    "dash_ranges_with_units": lambda n: "20tr-25tr " * (n // 10),
    "filler_words": lambda n: "của bạn là " * (n // 11) + "31 triệu",
    "unicode_decomposed": lambda n: "tầm ".replace("ầ", "à̂") * (n // 4) + "30tr",
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_skip_estimates_time_grows_roughly_linearly_with_input_size(shape: str) -> None:
    assert growth(SHAPES[shape]) < 8


def test_a_200k_char_answer_is_handled_by_the_guardrail() -> None:
    text = "dưới 30 triệu, máy 31 triệu. " * 7_000  # ~200k ký tự

    verdict = apply_guardrail(FinalAnswer(text=text), EVIDENCE)

    assert verdict.price_warnings == (31 * M,)
