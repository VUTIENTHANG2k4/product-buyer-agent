"""QA small-fixes-5: `allowed_write_tools` với câu hỏi tu từ ("làm gì/làm chi") và "sao phải"
(BUG-M7-6b).

Quy ước: tool ghi chỉ mở khi câu YÊU CẦU rõ ràng; câu mơ hồ thì đóng (agent hỏi lại), vì mở nhầm
là tự ý ghi vào danh sách/cảnh báo của người dùng. Test `xfail(strict=True)` mã `BUG-S5-n` là lỗi
đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải gỡ dấu xfail.
"""

import time
import unicodedata

import pytest

from app.agent.guardrail import ADD_TOOL, ALERT_TOOL, allowed_write_tools

NONE: frozenset[str] = frozenset()
ADD = frozenset({ADD_TOOL})
ALERT = frozenset({ALERT_TOOL})
BOTH = ADD | ALERT
TIME_BUDGET_S = 1.0


# ---------------------------------------------------------------- lời từ chối dạng câu hỏi tu từ
@pytest.mark.parametrize(
    "message",
    [
        "tôi thêm vào danh sách làm gì",
        "Tôi thêm vào danh sách làm gì?",
        "THÊM VÀO DANH SÁCH LÀM GÌ",
        "thêm vào danh sách làm chi",
        "thêm vào danh sách để làm gì",
        "thêm vào danh sách  làm   gì",
        "thêm vào danh sách\nlàm gì",
        "thêm vào danh sách làm gì đó?",
        "thêm vào danh sách làm gì nữa",
        "đặt cảnh báo làm gì",
        "đặt cảnh báo để làm gì",
        "đặt cảnh báo để làm gì đó?",
        "dat canh bao lam gi",
        "ＴＨÊＭ ＶÀＯ ＤＡＮＨ ＳÁＣＨ ＬÀＭ ＧÌ",
        unicodedata.normalize("NFD", "thêm vào danh sách làm gì"),
        unicodedata.normalize("NFD", "đặt cảnh báo để làm gì"),
        "lưu vào danh sách làm gì",
        "bật cảnh báo làm chi",
    ],
)
def test_a_rhetorical_question_right_after_the_request_keeps_the_write_tool_closed(
    message: str,
) -> None:
    assert allowed_write_tools(message) == NONE


@pytest.mark.parametrize(
    "message",
    [
        "thêm vào danh sách rồi làm gì tiếp",
        "thêm vào danh sách, làm gì tiếp theo?",
        "thêm vào danh sách. Làm gì tiếp?",
        "làm gì thì làm, thêm vào danh sách",
        "làm gì? thêm vào danh sách",
        "thêm vào danh sách làm gìn",
        "thêm vào danh sách làm quà",
        "thêm vào danh sách làm quà tặng sinh nhật",
        "thêm vào danh sách làm việc",
        "thêm vào danh sách làm ơn",
        "làm ơn thêm vào danh sách",
        "làm gì thì làm, đặt cảnh báo khi giá dưới 20 triệu",
        "đặt cảnh báo giúp tôi, mà làm gì tiếp?",
    ],
)
def test_other_uses_of_lam_do_not_turn_a_real_request_into_a_refusal(message: str) -> None:
    assert allowed_write_tools(message) & (ADD | ALERT) != NONE


def test_a_real_request_followed_by_a_rhetorical_one_for_the_same_tool_still_allows_it() -> None:
    assert allowed_write_tools("thêm vào danh sách làm gì rồi thêm vào danh sách") == ADD
    assert allowed_write_tools("thêm vào danh sách làm gì, thêm vào danh sách giúp tôi") == ADD
    assert allowed_write_tools("thêm vào danh sách để làm gì, thêm vào danh sách giúp tôi") == ADD


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("thêm vào danh sách làm gì, và đặt cảnh báo khi giá dưới 20tr", ALERT),
        ("đặt cảnh báo khi giá dưới 20 triệu, thêm vào danh sách làm gì", ALERT),
        ("tôi thêm vào danh sách làm gì, đặt cảnh báo giúp tôi khi giá dưới 20 triệu", ALERT),
        ("đặt cảnh báo làm gì, thêm vào danh sách giúp tôi", ADD),
        ("đặt cảnh báo làm gì, thêm vào danh sách làm gì", NONE),
        ("thêm vào danh sách giúp tôi, đặt cảnh báo khi giá dưới 20 triệu", BOTH),
    ],
)
def test_each_tool_is_judged_on_its_own_clause(message: str, expected: frozenset[str]) -> None:
    assert allowed_write_tools(message) == expected


# ---------------------------------------------------------------- "sao phải"
@pytest.mark.parametrize(
    "message",
    [
        "sao phải thêm vào danh sách",
        "Sao phải thêm vào danh sách?",
        "tại sao phải thêm vào danh sách",
        "sao phai them vao danh sach",
        "SAO PHẢI ĐẶT CẢNH BÁO",
        "sao phải  đặt  cảnh báo khi giá giảm",
        "sao phải thêm máy này vào danh sách",
        "sao phải đặt cảnh báo",
        "ＳＡＯ ＰＨẢＩ ＴＨÊＭ ＶÀＯ ＤＡＮＨ ＳÁＣＨ",
        unicodedata.normalize("NFD", "sao phải thêm vào danh sách"),
    ],
)
def test_sao_phai_before_the_verb_is_a_refusal(message: str) -> None:
    assert allowed_write_tools(message) == NONE


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("sao phải lo, đặt cảnh báo giúp tôi", ALERT),
        ("sao phải chờ? thêm vào danh sách giúp tôi", ADD),
        ("sao phải chờ lâu thế. Đặt cảnh báo khi giá dưới 20 triệu", ALERT),
        ("sao phải đặt cảnh báo, thêm vào danh sách giúp tôi", ADD),
        ("đặt cảnh báo giúp tôi, sao phải chờ", ALERT),
        ("thêm vào danh sách giúp tôi, sao phải đợi", ADD),
        ("thêm vào danh sách; sao phải đợi lâu thế", ADD),
    ],
)
def test_sao_phai_in_another_clause_does_not_block_the_request(
    message: str, expected: frozenset[str]
) -> None:
    assert allowed_write_tools(message) == expected


# ---------------------------------------------------------------- ca mơ hồ: đóng tool (an toàn)
@pytest.mark.parametrize(
    "message",
    [
        "thêm vào danh sách làm gì đó cho vui",
        "đặt cảnh báo làm gì đó khi giá giảm",
    ],
)
def test_ambiguous_lam_gi_do_after_the_request_fails_closed(message: str) -> None:
    # "làm gì đó" vừa là "để làm gì vậy" vừa là "làm một việc nào đó": chưa rõ là yêu cầu nên đóng.
    assert allowed_write_tools(message) == NONE


# ---------------------------------------------------------------- hiệu năng (ReDoS)
@pytest.mark.parametrize("count", [2_000, 20_000])
@pytest.mark.parametrize(
    "unit",
    [
        "them vao danh sach ",
        "sao phai ",
        "dat canh bao lam gi ",
        "them ",
        "dat ",
        "lam gi ",
        "sao phai x ",
        "thêm vào danh sách làm gì ",
    ],
)
def test_long_repetitive_messages_are_evaluated_within_the_time_budget(
    unit: str, count: int
) -> None:
    started = time.perf_counter()

    allowed_write_tools(unit * count)

    assert time.perf_counter() - started < TIME_BUDGET_S


@pytest.mark.parametrize(
    "message",
    [
        "x" * 200_000 + " thêm vào danh sách",
        "thêm " + "a" * 200_000 + " vào danh sách",
        "sao phải " + "a " * 100_000 + "thêm vào danh sách",
        "thêm vào danh sách" + " " * 200_000 + "làm gì",
        "thêm vào danh sách" + "\n" * 100_000 + "làm gì",
        "đặt " + "cảnh " * 50_000 + "báo",
        "khi " + "giá " * 50_000 + "giảm còn",
    ],
    ids=[
        "long-prefix",
        "long-gap-inside-request",
        "sao-phai-then-long-gap",
        "long-spaces-before-rhetorical",
        "long-newlines-before-rhetorical",
        "long-alert-verb-gap",
        "long-price-clause",
    ],
)
def test_long_messages_without_break_marks_are_evaluated_within_the_time_budget(
    message: str,
) -> None:
    started = time.perf_counter()

    allowed_write_tools(message)

    assert time.perf_counter() - started < TIME_BUDGET_S


# ---------------------------------------------------------------- lỗi đã tái hiện
@pytest.mark.parametrize(
    "message",
    [
        "sao tôi phải thêm vào danh sách",
        "sao mình phải thêm vào danh sách",
        "sao lại phải thêm vào danh sách",
        "tại sao tôi phải đặt cảnh báo",
        "Sao tôi lại phải đặt cảnh báo khi giá giảm",
    ],
)
def test_sao_with_a_subject_before_phai_is_a_refusal(message: str) -> None:
    assert allowed_write_tools(message) == NONE


@pytest.mark.parametrize(
    "message",
    [
        "why add it to my wishlist",
        "why should I add this to my shopping list",
        "why would I create an alert",
    ],
)
def test_english_rhetorical_questions_are_refusals(message: str) -> None:
    assert allowed_write_tools(message) == NONE
