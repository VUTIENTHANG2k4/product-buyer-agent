"""T9.5: thứ trong tuần của cron theo chuẩn crontab (0/7 = Chủ nhật, 1 = thứ Hai)."""

from datetime import UTC, datetime

import pytest

from app import worker

# 2026-10-23 là thứ Sáu.
MOMENT = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0 3 * * 1", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # thứ Hai (trước đây ra thứ Ba)
        ("0 3 * * 0", datetime(2026, 10, 25, 3, 0, tzinfo=UTC)),  # Chủ nhật
        ("0 3 * * 7", datetime(2026, 10, 25, 3, 0, tzinfo=UTC)),  # 7 cũng là Chủ nhật
        ("0 3 * * 5", datetime(2026, 10, 30, 3, 0, tzinfo=UTC)),  # thứ Sáu, đã qua 3 giờ hôm nay
        ("0 3 * * 6", datetime(2026, 10, 24, 3, 0, tzinfo=UTC)),  # thứ Bảy
        ("0 3 * * 1-5", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # bỏ qua cuối tuần
        ("0 3 * * 6,0", datetime(2026, 10, 24, 3, 0, tzinfo=UTC)),
        ("0 3 * * */2", datetime(2026, 10, 24, 3, 0, tzinfo=UTC)),  # CN, T3, T5, T7
        ("0 3 * * 1-5/2", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # T2, T4, T6: Sáu đã qua 3 giờ
        ("0 3 * * mon-fri", datetime(2026, 10, 26, 3, 0, tzinfo=UTC)),  # tên ngày giữ nguyên
        ("0 3 * * *", datetime(2026, 10, 24, 3, 0, tzinfo=UTC)),
    ],
)
def test_numeric_weekdays_follow_crontab_numbering(expression: str, expected: datetime) -> None:
    trigger = worker.parse_cron("X", expression)

    assert trigger.get_next_fire_time(None, MOMENT) == expected


@pytest.mark.parametrize(
    "expression", ["0 3 * * 8", "0 3 * * 5-1", "0 3 * * 1-5/0", "0 3 * * */-1"]
)
def test_out_of_range_numeric_weekdays_name_the_variable(expression: str) -> None:
    with pytest.raises(ValueError, match="CATALOG_REFRESH_CRON"):
        worker.parse_cron("CATALOG_REFRESH_CRON", expression)
