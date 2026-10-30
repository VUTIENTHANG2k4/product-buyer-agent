"""CLI ghép lại offer (`scripts/rematch.py`, T5.4): cờ và báo cáo. Logic ở test_rematch_service."""

import pytest

from app.domain.enums import Category, MatchMethod, SiteKey
from app.services.rematch_service import REMATCH_CATEGORIES, OfferMove, RematchReport
from scripts import rematch
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


class FakeSession:
    """Ghi lại commit/rollback; `Session(engine)` dùng như context manager."""

    instances: list["FakeSession"] = []

    def __init__(self, engine: object) -> None:
        self.events: list[str] = []
        FakeSession.instances.append(self)

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.events.append("close")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


class FakeEngine:
    disposed = False

    def dispose(self) -> None:
        FakeEngine.disposed = True


class StubService:
    calls: list[tuple[list[Category], SiteKey | None, bool]] = []
    error: Exception | None = None

    def __init__(self, session: FakeSession) -> None:
        pass

    def run(
        self, categories: list[Category], *, site: SiteKey | None, apply: bool
    ) -> RematchReport:
        StubService.calls.append((categories, site, apply))
        if StubService.error is not None:
            raise StubService.error
        return RematchReport(applied=apply, offers_checked=2)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> type[FakeSession]:
    FakeSession.instances = []
    FakeEngine.disposed = False
    StubService.calls = []
    StubService.error = None
    monkeypatch.setattr(rematch, "get_engine", lambda url: FakeEngine())
    monkeypatch.setattr(rematch, "Session", FakeSession)
    monkeypatch.setattr(rematch, "RematchService", StubService)
    return FakeSession


def test_dry_run_rolls_back_and_never_commits(
    wired: type[FakeSession], capsys: pytest.CaptureFixture[str]
) -> None:
    assert rematch.main([]) == 0

    assert wired.instances[0].events == ["rollback", "close"]
    assert StubService.calls == [(list(REMATCH_CATEGORIES), None, False)]
    assert FakeEngine.disposed
    assert "Chạy thử" in capsys.readouterr().out


def test_apply_commits_with_the_selected_category_and_site(
    wired: type[FakeSession], capsys: pytest.CaptureFixture[str]
) -> None:
    assert rematch.main(["--category", "mouse", "--site", "gearvn", "--apply"]) == 0

    assert wired.instances[0].events == ["commit", "close"]
    assert StubService.calls == [([Category.mouse], SiteKey.gearvn, True)]
    assert capsys.readouterr().out.startswith("Đã ghi")


def test_an_error_never_commits_and_still_disposes_the_engine(wired: type[FakeSession]) -> None:
    StubService.error = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        rematch.main(["--apply"])

    assert "commit" not in wired.instances[0].events
    assert FakeEngine.disposed
