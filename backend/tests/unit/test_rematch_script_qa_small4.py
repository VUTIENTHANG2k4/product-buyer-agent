"""QA small-fixes-4: CLI `scripts/rematch.py` (cờ, lỗi nhập, báo cáo tiếng Việt), Makefile.

Test `xfail(strict=True)` mã `BUG-S4-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import re
from pathlib import Path

import pytest

from app.domain.enums import Category, MatchMethod, SiteKey
from app.services.rematch_service import REMATCH_CATEGORIES, OfferMove, RematchReport
from scripts import rematch
from scripts.rematch import MAX_LISTED_MOVES, format_report, parse_args

MAKEFILE = Path(__file__).resolve().parents[3] / "Makefile"


def move(offer_id: int = 1, title: str = "Chuột Pulsar X2", to: int | None = 2) -> OfferMove:
    return OfferMove(offer_id, title, 1, to, MatchMethod.fuzzy)


# ---- cờ ----
@pytest.mark.parametrize("category", [c.value for c in REMATCH_CATEGORIES])
def test_every_tier_one_category_is_accepted(category: str) -> None:
    assert parse_args(["--category", category]).category == category


@pytest.mark.parametrize(
    "category", ["phone", "other", "Laptop", "MOUSE", "", "laptop,mouse", "all"]
)
def test_other_categories_and_spellings_are_rejected(category: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--category", category])
    assert exit_info.value.code == 2


@pytest.mark.parametrize("site", [s.value for s in SiteKey])
def test_every_site_key_is_accepted(site: str) -> None:
    assert parse_args(["--site", site]).site == site


@pytest.mark.parametrize(
    "argv",
    [
        ["--site", "GearVN"],
        ["--site"],
        ["--category"],
        ["--apply=1"],
        ["--apply", "yes"],
        ["--dry-run"],
        ["apply"],
        ["--unknown"],
    ],
)
def test_malformed_input_exits_with_usage_error_code_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_args(argv)
    assert exit_info.value.code == 2


def test_the_last_of_a_repeated_category_flag_wins() -> None:
    args = parse_args(["--category", "laptop", "--category", "mouse"])

    assert args.category == "mouse"


@pytest.mark.parametrize("flag", ["--a", "--ap", "--app", "--appl"])
def test_the_destructive_apply_flag_cannot_be_triggered_by_an_abbreviation(flag: str) -> None:
    with pytest.raises(SystemExit):
        parse_args([flag])


def test_invalid_input_stops_before_any_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(url: str) -> None:
        raise AssertionError("must not open the database on bad input")

    monkeypatch.setattr(rematch, "get_engine", forbidden)

    with pytest.raises(SystemExit):
        rematch.main(["--category", "phone", "--apply"])


# ---- Makefile ----
def test_make_rematch_only_writes_when_apply_is_exactly_one() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    recipe = next(line for line in text.splitlines() if "scripts.rematch" in line)

    assert "$(if $(filter 1,$(APPLY)),--apply)" in recipe
    assert recipe.count("--apply") == 1
    assert re.search(r"\$\(if \$\(CAT\),--category \$\(CAT\)\)", recipe)
    assert re.search(r"\$\(if \$\(SITE\),--site \$\(SITE\)\)", recipe)


# ---- báo cáo ----
def test_a_move_line_stays_on_one_line_for_titles_with_control_characters() -> None:
    title = "Chuột\nPulsar\tX2\x1b[31m đỏ \r\n" + "x" * 200
    lines = format_report(RematchReport(applied=False, moves=[move(title=title)]))

    move_lines = [line for line in lines if "offer #1 " in line]
    assert len(move_lines) == 1
    assert "\n" not in move_lines[0] and "\r" not in move_lines[0]
    assert "\x1b" not in move_lines[0]
    assert len(move_lines[0]) < 160


def test_a_move_line_keeps_vietnamese_text_readable() -> None:
    lines = format_report(
        RematchReport(applied=True, moves=[move(title="Chuột không dây Đen"), move(2, "x", None)])
    )

    assert any("'Chuột không dây Đen': #1 → #2 (fuzzy)" in line for line in lines)
    assert any(line.endswith("#1 → sản phẩm mới (fuzzy)") for line in lines)


@pytest.mark.parametrize(
    ("count", "tail"), [(MAX_LISTED_MOVES, None), (MAX_LISTED_MOVES + 1, "… và 1 offer khác")]
)
def test_the_move_list_is_cut_exactly_at_the_page_size(count: int, tail: str | None) -> None:
    moves = [move(i) for i in range(count)]

    lines = format_report(RematchReport(applied=True, moves=moves))

    assert sum("offer #" in line for line in lines) == min(count, MAX_LISTED_MOVES)
    assert (tail in lines[-1]) if tail else all("… và" not in line for line in lines)


def test_headline_counts_match_the_report_fields() -> None:
    report = RematchReport(
        applied=True,
        offers_checked=7,
        moves=[move(1), move(2)],
        products_created=3,
        products_renamed=[1, 2, 3, 4],
        products_specs_changed=[5],
        products_deleted=[8, 9],
    )

    text = "\n".join(format_report(report))

    assert text.startswith("Đã ghi: xét 7 offer.")
    assert "Chuyển sản phẩm: 2 offer" in text
    assert "Sản phẩm mới: 3" in text
    assert "Sửa hãng/tên/mã: 4 sản phẩm" in text
    assert "Dựng lại thông số khác trước: 1 sản phẩm" in text
    assert "Xóa sản phẩm không còn offer: 2" in text
    assert "Không có gì thay đổi." not in text


def test_kept_orphans_are_listed_even_when_nothing_else_changed() -> None:
    lines = format_report(RematchReport(applied=False, orphans_kept=[12, 3]))

    assert any(line.endswith("(không còn offer): #12, #3") for line in lines)
    assert lines[-1] == "Không có gì thay đổi."


def test_a_dry_run_report_tells_how_to_apply_and_an_applied_one_does_not() -> None:
    dry = "\n".join(format_report(RematchReport(applied=False)))
    applied = "\n".join(format_report(RematchReport(applied=True)))

    assert "thêm --apply để ghi" in dry
    assert "--apply" not in applied and applied.startswith("Đã ghi")


def test_main_prints_the_report_to_stdout_in_vietnamese(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Engine:
        def dispose(self) -> None:
            pass

    class Session:
        def __init__(self, engine: object) -> None:
            pass

        def __enter__(self) -> "Session":
            return self

        def __exit__(self, *exc: object) -> None:
            pass

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

    class Service:
        def __init__(self, session: Session) -> None:
            pass

        def run(
            self, categories: list[Category], *, site: SiteKey | None, apply: bool
        ) -> RematchReport:
            return RematchReport(applied=apply, offers_checked=1, moves=[move(title="Chuột Đen")])

    monkeypatch.setattr(rematch, "get_engine", lambda url: Engine())
    monkeypatch.setattr(rematch, "Session", Session)
    monkeypatch.setattr(rematch, "RematchService", Service)

    assert rematch.main(["--category", "mouse"]) == 0

    out = capsys.readouterr().out
    assert "Chạy thử" in out and "'Chuột Đen'" in out and out.endswith("\n")
