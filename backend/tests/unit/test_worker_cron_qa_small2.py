"""QA lượt việc nhỏ 2 (T9.5): thứ trong tuần của cron theo chuẩn crontab, biên và đầu vào lạ.

Quy ước crontab: 0 và 7 = Chủ nhật, 1 = thứ Hai … 6 = thứ Bảy (APScheduler đánh số lệch: 0 = thứ
Hai). Test đỏ do lỗi ứng dụng giữ bằng `xfail(strict=True)` mã `BUG-S2-n`.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app import worker

# 2026-10-23 là thứ Sáu; 12:00 UTC nên mốc 03:00 hôm nay đã qua.
MOMENT = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
CRON_DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def crontab_weekday(moment: datetime) -> int:
    """Thứ của `moment` theo crontab (0 = Chủ nhật)."""
    return (moment.weekday() + 1) % 7


def fire_weekdays(expression: str, count: int = 14) -> set[int]:
    """Các thứ (theo crontab) mà lịch thực sự chạy trong `count` lượt kế tiếp."""
    trigger = worker.parse_cron("X", expression)
    weekdays: set[int] = set()
    previous = None
    moment = MOMENT
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, moment)
        assert fire is not None
        weekdays.add(crontab_weekday(fire))
        previous, moment = fire, fire + timedelta(minutes=1)
    return weekdays


# ---------------------------------------------------------------- từng số 0..7
@pytest.mark.parametrize("number", range(8))
def test_every_single_weekday_number_fires_only_on_that_crontab_weekday(number: int) -> None:
    assert fire_weekdays(f"0 3 * * {number}") == {number % 7}


@pytest.mark.parametrize("number", range(8))
def test_a_number_and_its_english_name_give_the_same_schedule(number: int) -> None:
    name = CRON_DAY_NAMES[number % 7]
    numeric = worker.parse_cron("X", f"0 3 * * {number}")
    named = worker.parse_cron("X", f"0 3 * * {name}")

    assert numeric.get_next_fire_time(None, MOMENT) == named.get_next_fire_time(None, MOMENT)


@pytest.mark.parametrize(
    ("expression", "weekdays"),
    [
        ("1,3,5", {1, 3, 5}),
        ("5,1,3", {1, 3, 5}),  # không theo thứ tự
        ("1,1,1", {1}),  # trùng lặp
        ("0,7", {0}),  # hai cách viết cùng Chủ nhật
        ("0-7", set(range(7))),
        ("1-7", set(range(7))),  # thứ Hai đến Chủ nhật (7)
        ("5-7", {5, 6, 0}),  # đi qua Chủ nhật bằng số 7
        ("2-4", {2, 3, 4}),
        ("3-3", {3}),
        ("*/2", {0, 2, 4, 6}),
        ("*/3", {0, 3, 6}),
        ("*/7", {0}),
        ("*/1", set(range(7))),
        ("1-6/2", {1, 3, 5}),
        ("0-6/3", {0, 3, 6}),
        ("1-5/2,6", {1, 3, 5, 6}),  # bước + phần tử đơn
        ("1-2,4-5", {1, 2, 4, 5}),
    ],
)
def test_lists_ranges_and_steps_follow_crontab_numbering(
    expression: str, weekdays: set[int]
) -> None:
    assert fire_weekdays(f"0 3 * * {expression}") == weekdays


# ---------------------------------------------------------------- giá trị cụ thể với ngày cố định
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0 3 * * 2", datetime(2026, 10, 27, 3, 0, tzinfo=UTC)),  # thứ Ba
        ("0 3 * * 3", datetime(2026, 10, 28, 3, 0, tzinfo=UTC)),  # thứ Tư
        ("0 3 * * 4", datetime(2026, 10, 29, 3, 0, tzinfo=UTC)),  # thứ Năm
        ("30 23 * * 5", datetime(2026, 10, 23, 23, 30, tzinfo=UTC)),  # thứ Sáu, còn trong hôm nay
        ("0 3 * * 07", datetime(2026, 10, 25, 3, 0, tzinfo=UTC)),  # số 0 đứng đầu
        ("  0   3  *  *   1  ", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # nhiều khoảng trắng
        ("0\t3\t*\t*\t1", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # tab
        ("0 3 * * MON", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # tên viết hoa
        ("0 3 * * Sun", datetime(2026, 10, 25, 3, 0, tzinfo=UTC)),
        ("0 3 * * mon,fri", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # danh sách tên
        ("0 3 * * sat-sun", datetime(2026, 10, 24, 3, 0, tzinfo=UTC)),
    ],
)
def test_next_fire_time_for_fixed_moment(expression: str, expected: datetime) -> None:
    assert worker.parse_cron("X", expression).get_next_fire_time(None, MOMENT) == expected


def test_the_fire_time_is_in_utc() -> None:
    fire = worker.parse_cron("X", "0 3 * * 1").get_next_fire_time(None, MOMENT)

    assert fire is not None and fire.utcoffset() == timedelta(0)


def test_other_fields_are_not_touched_by_the_weekday_conversion() -> None:
    fire = worker.parse_cron("X", "*/15 6-8 * * 1").get_next_fire_time(None, MOMENT)

    assert fire == datetime(2026, 10, 26, 6, 0, tzinfo=UTC)


def test_day_of_month_with_weekday_number_uses_crontab_numbering() -> None:
    # Ngày 26/10/2026 là thứ Hai; APScheduler gộp ngày-trong-tháng và thứ bằng AND.
    fire = worker.parse_cron("X", "0 3 26 10 1").get_next_fire_time(None, MOMENT)

    assert fire == datetime(2026, 10, 26, 3, 0, tzinfo=UTC)


# ---------------------------------------------------------------- lỗi luôn nêu tên biến
BAD_EXPRESSIONS = [
    "0 3 * * 8",  # ngoài miền
    "0 3 * * 99999999999999999999",  # số khổng lồ
    "0 3 * * " + "9" * 5000,  # vượt giới hạn đổi chuỗi → số nguyên của Python
    "0 3 * * 5-1",  # khoảng ngược
    "0 3 * * 7-0",
    "0 3 * * 1-",
    "0 3 * * -1",
    "0 3 * * 1,",
    "0 3 * * ,1",
    "0 3 * * 1,,2",
    "0 3 * * */0",
    "0 3 * * 1-5/0",
    "0 3 * * */",
    "0 3 * * 1-5-6",
    "0 3 * * 1//2",
    "0 3 * * 7/2",
    "0 3 * * *-3",
    "0 3 * * #",
    "0 3 * * 1;",
    "0 3 * * ?",
    "0 3 * * L",
    "0 3 * * 5L",
    "0 3 * * 5#2",
    "0 3 * * funday",
    "0 3 * * 1\x00",
    "0 3 * * 🗓️",
    "0 3 * * 1 2",  # thừa trường
    "0 3 * *",  # thiếu trường
    "@weekly",
    "",
    "   ",
    "0 0 31 2 *",  # không bao giờ chạy
]


@pytest.mark.parametrize("expression", BAD_EXPRESSIONS)
def test_every_bad_expression_raises_value_error_naming_the_variable(expression: str) -> None:
    with pytest.raises(ValueError, match="CATALOG_REFRESH_CRON không hợp lệ"):
        worker.parse_cron("CATALOG_REFRESH_CRON", expression)


def test_error_message_quotes_the_offending_expression() -> None:
    with pytest.raises(ValueError, match=r"0 3 \* \* 9"):
        worker.parse_cron("PRICE_CRON", "0 3 * * 9")


def test_a_very_long_valid_weekday_list_is_parsed_quickly_and_correctly() -> None:
    expression = "0 3 * * " + ",".join(["1"] * 50_000)

    assert worker.parse_cron("X", expression).get_next_fire_time(None, MOMENT) == datetime(
        2026, 10, 26, 3, 0, tzinfo=UTC
    )


def test_a_very_long_garbage_field_fails_cleanly() -> None:
    with pytest.raises(ValueError, match="X không hợp lệ"):
        worker.parse_cron("X", "0 3 * * " + "1-" * 50_000)


# ---------------------------------------------------------------- trộn tên và số (BUG-S2-1)
@pytest.mark.parametrize(
    ("expression", "weekdays"),
    [
        ("fri,1", {5, 1}),  # crontab: thứ Sáu + thứ Hai
        ("1,fri", {5, 1}),
        ("sun,1-2", {0, 1, 2}),
        ("mon-3", {1, 2, 3}),  # thứ Hai đến thứ Tư (3)
    ],
)
def test_mixed_names_and_numbers_use_crontab_numbering(expression: str, weekdays: set[int]) -> None:
    assert fire_weekdays(f"0 3 * * {expression}") == weekdays


def test_mixed_names_and_numbers_are_either_correct_or_rejected() -> None:
    try:
        weekdays = fire_weekdays("0 3 * * fri,1")
    except ValueError:
        return
    assert weekdays == {5, 1}
