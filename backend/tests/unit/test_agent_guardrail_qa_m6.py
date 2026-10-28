"""QA M6: regex guardrail (quyền tool ghi, link trong văn bản), bằng chứng từ tool, ngưỡng giá."""

import time
import unicodedata

import pytest
from pydantic import ValidationError

from app.agent.guardrail import (
    ADD_TOOL,
    ALERT_TOOL,
    REMOVED_LINK,
    Evidence,
    allowed_write_tools,
    apply_guardrail,
    check_write_args,
)
from app.agent.schemas import FinalAnswer, LiveItem

ZWSP = chr(0x200B)  # ký tự vô hình (nhóm Cf)


def evidence() -> Evidence:
    found = Evidence()
    found.add_result(
        "search_catalog",
        {
            "ok": True,
            "items": [
                {
                    "product_id": 1,
                    "best_offer": {"price": 20_000_000, "url": "https://a.example/p/1"},
                },
                {
                    "product_id": 2,
                    "best_offer": {"price": 25_000_000, "url": "https://a.example/p/2?ref=x&b=1"},
                },
                {"product_id": 3, "best_offer": {"price": 9, "url": "https://a.example/p/3_"}},
            ],
        },
    )
    return found


def cleaned(text: str) -> str:
    return apply_guardrail(FinalAnswer(text=text), evidence()).answer.text


# ---- quyền tool ghi: dạng viết ----
@pytest.mark.parametrize(
    "message",
    [
        "THÊM MÁY ĐẦU TIÊN VÀO DANH SÁCH",
        unicodedata.normalize("NFD", "thêm máy này vào danh sách mua"),
        "thêm máy này vào danh sách mua".replace("thêm", "th" + ZWSP + "êm"),
        "thêm\tmáy\nnày vào  danh   sách",
        "Add the first one to my shopping list",
        "ＴＨÊＭ máy này vào danh sách",
    ],
)
def test_explicit_add_request_is_recognised_in_every_spelling(message: str) -> None:
    assert allowed_write_tools(message) == {ADD_TOOL}


@pytest.mark.parametrize(
    "message",
    [
        "Báo tôi khi máy này xuống dưới 20 triệu",
        "NHẮC TÔI NẾU GIÁ GIẢM",
        "thông báo cho tôi khi giá giảm",
        "báo cho mình khi có khuyến mãi",
        "Please notify me when it drops",
        "tôi muốn theo dõi giá máy đầu tiên",
        unicodedata.normalize("NFD", "đặt cảnh báo giá cho máy thứ 2"),
        "set an alert at 20 million",
    ],
)
def test_explicit_alert_request_is_recognised_in_every_spelling(message: str) -> None:
    assert allowed_write_tools(message) == {ALERT_TOOL}


# ---- BUG-M6-7: câu chỉ đọc có chữ "báo tôi"/"thông báo" không được mở khóa tool ghi ----
@pytest.mark.parametrize(
    "message",
    [
        "báo tôi giá hiện tại của máy đầu tiên",
        "hãy bảo tôi laptop nào tốt nhất",
        "thông báo cho tôi biết cấu hình của máy này",
        "nhắc tôi lại cấu hình máy thứ 2",
        "báo cho tôi biết máy nào rẻ nhất",
    ],
)
def test_read_only_requests_containing_tell_me_do_not_unlock_the_alert_tool(
    message: str,
) -> None:
    assert allowed_write_tools(message) == frozenset()


def test_write_request_must_be_in_one_sentence() -> None:
    assert allowed_write_tools("Thêm vài lựa chọn nữa. Cho tôi xem danh sách mua.") == frozenset()
    assert allowed_write_tools("Tìm laptop rẻ nhất. Thêm máy đầu tiên vào danh sách.") == {ADD_TOOL}


@pytest.mark.parametrize(
    "message",
    [
        "đừng thêm vào danh sách mua, chỉ so sánh thôi",
        "không cần đặt cảnh báo nhé",
        "tôi không muốn thêm máy này vào danh sách",
        "do not add it to my wishlist",
        "Please don't set an alert",
        "ĐỪNG THÊM MÁY NÀY VÀO DANH SÁCH",
        unicodedata.normalize("NFD", "đừng đặt cảnh báo giá"),
        "không đặt cảnh báo",
        "không thêm vào danh sách",
        "khỏi thêm vào danh sách",
        "tôi không nghĩ nên thêm vào danh sách",
        "Đừng thêm Lenovo Legion Pro 5 16IRX9 RTX 4070 vào danh sách",
    ],
)
def test_negated_write_request_does_not_unlock_a_write_tool(message: str) -> None:
    assert allowed_write_tools(message) == frozenset()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Đừng lo, thêm máy này vào danh sách giúp tôi", {ADD_TOOL}),
        ("Đừng thêm máy thứ 2. Thêm máy đầu tiên vào danh sách.", {ADD_TOOL}),
        ("không cần so sánh nữa, đặt cảnh báo giá cho máy đầu tiên", {ALERT_TOOL}),
        ("Không biết máy nào tốt? Thêm máy đầu tiên vào danh sách", {ADD_TOOL}),
        ("Đừng thêm vào danh sách, nhưng hãy đặt cảnh báo giá", {ALERT_TOOL}),
        ("tìm laptop không quá 30 triệu và đặt cảnh báo giá", {ALERT_TOOL}),
        ("thêm Lenovo Legion Pro 5 16IRX9 RTX 4070 vào danh sách", {ADD_TOOL}),
    ],
)
def test_negation_only_cancels_the_request_it_belongs_to(message: str, expected: set[str]) -> None:
    assert allowed_write_tools(message) == expected


# ---- T6.9: ngưỡng cảnh báo sai thang ----
@pytest.mark.parametrize(
    ("price", "amounts"),
    [
        (25, set()),  # nhỏ hơn 10.000 luôn sai, kể cả khi người dùng không nêu số tiền
        (9_999, {25_000_000}),
        (25, {25_000_000}),  # "25 triệu" mà LLM gửi 25
        (25_000, {25_000_000}),  # "25 triệu" mà LLM gửi 25 nghìn
    ],
)
def test_alert_threshold_in_the_wrong_unit_is_rejected(price: int, amounts: set[int]) -> None:
    result = check_write_args(ALERT_TOOL, {"target_price": price}, amounts)

    assert result is not None
    assert result["error"] == "INVALID_TARGET_PRICE"


@pytest.mark.parametrize(
    ("tool", "args", "amounts"),
    [
        (ALERT_TOOL, {"target_price": 25_000_000}, {25_000_000}),
        (ALERT_TOOL, {"target_price": 24_000_000}, {25_000_000}),  # "rẻ hơn 1 triệu": hợp lệ
        (ALERT_TOOL, {"target_price": 10_000}, set()),
        (ALERT_TOOL, {"target_price": "25"}, {25_000_000}),  # sai kiểu: để tool báo lỗi tham số
        (ALERT_TOOL, {"target_price": True}, set()),
        (ALERT_TOOL, {}, set()),
        (ADD_TOOL, {"target_price": 25}, set()),  # chỉ áp cho create_price_alert
    ],
)
def test_valid_or_unrelated_write_arguments_pass(
    tool: str, args: dict[str, object], amounts: set[int]
) -> None:
    assert check_write_args(tool, args, amounts) is None


def test_regexes_stay_linear_on_long_hostile_input() -> None:
    hostile = ("thêm " * 40_000) + ("báo tôi " * 40_000) + "x" * 100_000
    started = time.perf_counter()
    allowed_write_tools(hostile)
    apply_guardrail(FinalAnswer(text=hostile + " https://" + "a" * 100_000), evidence())
    # Cỡ 0,5 s khi chạy riêng, ~2,5 s dưới coverage; backtracking thật mất hàng phút.
    assert time.perf_counter() - started < 15.0


# ---- link trong văn bản (BUG-M6-2) ----
@pytest.mark.parametrize(
    "link",
    [
        "HTTPS://EVIL.EXAMPLE/buy",
        "Http://evil.example/buy",
        "www.evil.example/buy",
        "WWW.EVIL.EXAMPLE",
    ],
)
def test_foreign_links_are_removed_whatever_the_case_or_scheme(link: str) -> None:
    verdict = apply_guardrail(FinalAnswer(text=f"Mua tại {link} nhé"), evidence())
    assert verdict.answer.text == f"Mua tại {REMOVED_LINK} nhé"
    assert verdict.dropped_text_urls == (link,)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("**https://a.example/p/1**", "**https://a.example/p/1**"),
        ("_https://a.example/p/1_", "_https://a.example/p/1_"),
        ("Xem https://a.example/p/1.", "Xem https://a.example/p/1."),
        ("(https://a.example/p/1)", "(https://a.example/p/1)"),
        ("[a](https://a.example/p/2?ref=x&b=1)", "[a](https://a.example/p/2?ref=x&b=1)"),
        ("<https://a.example/p/1>", "<https://a.example/p/1>"),
        ("https://a.example/p/3_", "https://a.example/p/3_"),  # link thật tự kết thúc bằng '_'
        ("giá tốt: https://a.example/p/1, https://a.example/p/2?ref=x&b=1;", None),
    ],
)
def test_links_from_tool_results_survive_markdown_and_punctuation(
    text: str, expected: str | None
) -> None:
    result = apply_guardrail(FinalAnswer(text=text), evidence())
    assert result.answer.text == (text if expected is None else expected)
    assert result.dropped_text_urls == ()


@pytest.mark.parametrize(
    "link",
    [
        "https://a.example/p/10",  # tiền tố của link thật
        "https://a.example/p/1/",
        "https://a.example/p/1#frag",
        "https://a.example/p/1?utm_source=x",
        "https://a.example.evil.example/p/1",
        "https://a.example/p/2?ref=x",
        "![ảnh](https://evil.example/pixel.png)",
    ],
)
def test_near_miss_links_are_not_treated_as_known(link: str) -> None:
    result = apply_guardrail(FinalAnswer(text=f"xem {link}"), evidence())
    assert REMOVED_LINK in result.answer.text
    assert result.dropped_text_urls


def test_several_foreign_links_are_all_reported_in_order() -> None:
    text = "a https://x.example/1 b https://a.example/p/1 c HTTP://y.example/2."
    verdict = apply_guardrail(FinalAnswer(text=text), evidence())
    assert verdict.dropped_text_urls == ("https://x.example/1", "HTTP://y.example/2")
    assert verdict.answer.text == (f"a {REMOVED_LINK} b https://a.example/p/1 c {REMOVED_LINK}.")


# ---- dữ liệu web là dữ liệu: không biến thành bằng chứng ----
def test_urls_and_ids_written_inside_names_never_become_evidence() -> None:
    found = Evidence()
    found.add_result(
        "search_catalog",
        {
            "ok": True,
            "items": [
                {
                    "product_id": 5,
                    "name": "Laptop https://evil.example/pay product_id=99 price=1",
                    "best_offer": {"url": "https://a.example/p/5", "price": 20_000_000},
                    "notes": ["url: https://evil.example/x", {"text": "product_id 77"}],
                }
            ],
        },
    )
    assert found.product_ids == {5}
    assert found.urls == {"https://a.example/p/5"}
    answer = FinalAnswer(text="Mua ở https://evil.example/pay", product_ids=[5, 99, 77])
    verdict = apply_guardrail(answer, found)
    assert verdict.answer.product_ids == [5]
    assert verdict.dropped_product_ids == (99, 77)
    assert verdict.dropped_text_urls == ("https://evil.example/pay",)


@pytest.mark.parametrize("value", ["7", 7.0, None, [7], {"id": 7}, True, False])
def test_only_real_integers_count_as_product_ids_and_prices(value: object) -> None:
    found = Evidence()
    found.add_result("x", {"ok": True, "product_id": value, "price": value})
    assert (found.product_ids, found.prices) == (set(), set())


@pytest.mark.parametrize("value", [7, 7.5, None, ["https://a.example/1"], True])
def test_only_string_values_count_as_urls(value: object) -> None:
    found = Evidence()
    found.add_result("live_search_other", {"ok": True, "url": value})
    assert (found.urls, found.live_urls) == (set(), set())


def test_failed_tool_result_with_nested_ids_adds_nothing() -> None:
    found = Evidence()
    found.add_result(
        "get_product_detail",
        {"ok": False, "error": "X", "details": {"product_id": 8, "url": "https://a.example/8"}},
    )
    assert (found.product_ids, found.urls, found.prices) == (set(), set(), set())


def test_live_items_with_foreign_urls_are_dropped_even_when_the_site_name_looks_real() -> None:
    found = Evidence()
    found.add_result("live_search_other", {"ok": True, "items": [{"url": "https://l.example/1"}]})
    answer = FinalAnswer(
        text="x",
        live_items=[
            LiveItem(site="shopee", title="thật", url="https://l.example/1"),
            LiveItem(site="shopee", title="chữ hoa", url="HTTPS://L.EXAMPLE/1"),
            LiveItem(site="shopee", title="javascript", url="javascript:alert(1)"),
        ],
    )
    verdict = apply_guardrail(answer, found)
    assert [item.title for item in verdict.answer.live_items] == ["thật"]
    assert len(verdict.dropped_live_urls) == 2


# ---- ngưỡng giá 1% ----
@pytest.mark.parametrize(
    ("text", "warned"),
    [
        ("Giá 20.200.000 ₫", ()),  # đúng 1%
        ("Giá 20.200.001 ₫", (20_200_001,)),
        ("Giá 19.800.000 ₫", ()),
        ("Giá 19.799.999 ₫", (19_799_999,)),
    ],
)
def test_one_percent_tolerance_is_inclusive(text: str, warned: tuple[int, ...]) -> None:
    found = Evidence(prices={20_000_000})
    assert apply_guardrail(FinalAnswer(text=text), found).price_warnings == warned


def test_price_warnings_are_sorted_and_deduplicated() -> None:
    text = "30 triệu, 18 triệu, 18.000.000đ, 30tr"
    verdict = apply_guardrail(FinalAnswer(text=text), Evidence(prices={20_000_000}))
    assert verdict.price_warnings == (18_000_000, 30_000_000)


def test_nonpositive_reference_prices_never_excuse_an_amount() -> None:
    verdict = apply_guardrail(FinalAnswer(text="Giá 12.000 ₫"), Evidence(prices={0, -5}))
    assert verdict.price_warnings == (12_000,)


# ---- câu trả lời ----
def test_duplicate_ids_are_reported_once_and_order_is_kept() -> None:
    answer = FinalAnswer(text="x", product_ids=[3, 99, 99, 1, 3, 98, 99])
    verdict = apply_guardrail(answer, evidence())
    assert verdict.answer.product_ids == [3, 1]
    assert verdict.dropped_product_ids == (99, 98)


def test_unknown_ids_with_valid_live_items_still_count_as_hallucination() -> None:
    found = Evidence()
    found.add_result("live_search_other", {"ok": True, "items": [{"url": "https://l.example/1"}]})
    answer = FinalAnswer(
        text="x",
        product_ids=[404],
        live_items=[LiveItem(site="s", title="t", url="https://l.example/1")],
    )
    verdict = apply_guardrail(answer, found)
    assert verdict.hallucinated is True
    assert len(verdict.answer.live_items) == 1


@pytest.mark.parametrize("text", ["", "   \n"])
def test_final_answer_text_cannot_be_blank(text: str) -> None:
    with pytest.raises(ValidationError):
        FinalAnswer(text=text, product_ids=[1])
