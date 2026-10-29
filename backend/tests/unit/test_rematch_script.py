"""CLI ghép lại offer (`scripts/rematch.py`, T5.4): cờ và báo cáo. Logic ở test_rematch_service."""

import pytest

from app.domain.enums import MatchMethod
from app.services.rematch_service import OfferMove, RematchReport
from scripts.rematch import MAX_LISTED_MOVES, format_report, parse_args


def test_default_is_a_dry_run_over_every_tier_one_category() -> None:
    args = parse_args([])
    assert (args.category, args.site, args.apply) == (None, None, False)


def test_flags_select_category_site_and_apply() -> None:
    args = parse_args(["--category", "mouse", "--site", "gearvn", "--apply"])
    assert (args.category, args.site, args.apply) == ("mouse", "gearvn", True)


@pytest.mark.parametrize("argv", [["--category", "phone"], ["--site", "nowhere"]])
def test_unknown_category_or_site_is_rejected(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_report_of_a_dry_run_says_nothing_was_written() -> None:
    report = RematchReport(
        applied=False,
        offers_checked=3,
        moves=[OfferMove(7, "Chuột Pulsar X2 Mini", 1, None, MatchMethod.new)],
        products_created=1,
        orphans_kept=[4],
    )
    text = "\n".join(format_report(report))
    assert text.startswith("Chạy thử (chưa ghi; thêm --apply để ghi): xét 3 offer.")
    assert "offer #7 'Chuột Pulsar X2 Mini': #1 → sản phẩm mới (new)" in text
    assert "Giữ lại vì còn trong danh sách mua/cảnh báo (không còn offer): #4" in text


def test_report_lists_at_most_a_page_of_moves_and_says_when_nothing_changed() -> None:
    moves = [OfferMove(i, "x", 1, 2, MatchMethod.fuzzy) for i in range(MAX_LISTED_MOVES + 5)]
    text = "\n".join(format_report(RematchReport(applied=True, moves=moves)))
    assert text.count("offer #") == MAX_LISTED_MOVES
    assert "… và 5 offer khác" in text
    assert format_report(RematchReport(applied=True))[-1] == "Không có gì thay đổi."
