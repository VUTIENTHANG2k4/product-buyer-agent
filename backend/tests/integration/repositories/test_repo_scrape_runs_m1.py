"""QA M1: test biên cho `ScrapeRunRepository` (set_status, bộ đếm, lượt gần nhất)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.repositories.scrape_runs import FINISHED_STATUSES, ScrapeRunRepository
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _run(repo: ScrapeRunRepository, *, hours: int = 0, **kwargs: Any) -> Any:
    return repo.create(
        kwargs.pop("site", SiteKey.mockshop),
        kwargs.pop("category", Category.laptop),
        ScrapeTrigger.test,
        now=T0 + timedelta(hours=hours),
        **kwargs,
    )


def test_finished_statuses_match_the_documented_terminal_states() -> None:
    assert {
        ScrapeStatus.SUCCEEDED,
        ScrapeStatus.PARTIAL,
        ScrapeStatus.FAILED,
        ScrapeStatus.BLOCKED,
    } == FINISHED_STATUSES


@pytest.mark.parametrize("previous", list(ScrapeStatus))
@pytest.mark.parametrize("status", list(ScrapeStatus))
def test_set_status_sets_finished_at_only_for_terminal_statuses_from_any_previous_status(
    db_session: Session, previous: ScrapeStatus, status: ScrapeStatus
) -> None:
    repo = ScrapeRunRepository(db_session)
    run = _run(repo)
    repo.set_status(run, previous, now=T0 + timedelta(minutes=1))

    repo.set_status(run, status, now=T0 + timedelta(minutes=9))
    db_session.expire(run)

    expected = T0 + timedelta(minutes=9) if status in FINISHED_STATUSES else None
    assert (run.status, run.finished_at) == (status, expected)


def test_set_status_blocked_after_needs_human_drops_challenge_unless_passed_again(
    db_session: Session,
) -> None:
    """Ghi nhận hành vi đã ghi ở docs/04 §3: `challenge=None` là xóa."""
    repo = ScrapeRunRepository(db_session)
    run = _run(repo)
    challenge = {"kind": "captcha", "image": "/captcha/1.png", "hỏi": "tổng 3 + 4?"}
    repo.set_status(run, ScrapeStatus.NEEDS_HUMAN, challenge=challenge)
    db_session.expire(run)
    assert run.challenge == challenge

    repo.set_status(run, ScrapeStatus.BLOCKED, error_message="captcha không được giải")
    db_session.expire(run)

    assert (run.challenge, run.error_message) == (None, "captcha không được giải")


def test_set_status_stores_very_long_unicode_error_message(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    run = _run(repo)
    message = "Lỗi: không đọc được trang 😀 " * 20_000

    repo.set_status(run, ScrapeStatus.FAILED, error_message=message, now=T0)
    db_session.expire(run)

    assert run.error_message == message


def test_set_status_with_an_empty_challenge_dict_keeps_an_empty_object_not_null(
    db_session: Session,
) -> None:
    repo = ScrapeRunRepository(db_session)
    run = _run(repo)

    repo.set_status(run, ScrapeStatus.NEEDS_HUMAN, challenge={})
    db_session.expire(run)

    assert run.challenge == {}


def test_update_counters_zero_is_applied_and_negative_is_rejected(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    run = _run(repo)
    repo.update_counters(run, pages_fetched=5, items_parsed=100)

    repo.update_counters(run, pages_fetched=0)
    db_session.expire(run)
    assert (run.pages_fetched, run.items_parsed) == (0, 100)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        repo.update_counters(run, items_failed=-1)


def test_latest_breaks_ties_of_started_at_by_id(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    _run(repo)
    newest = _run(repo)

    assert repo.latest(SiteKey.mockshop, Category.laptop) is newest
    assert repo.list_recent(limit=1) == [newest]


def test_latest_succeeded_ignores_a_newer_partial_or_failed_run(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    good = _run(repo, hours=0)
    repo.set_status(good, ScrapeStatus.SUCCEEDED, now=T0)
    for hours, status in ((1, ScrapeStatus.PARTIAL), (2, ScrapeStatus.FAILED)):
        repo.set_status(_run(repo, hours=hours), status, now=T0)

    assert repo.latest_succeeded(SiteKey.mockshop, Category.laptop) is good
    assert repo.latest_succeeded(SiteKey.mockshop, Category.mouse) is None


def test_latest_blocked_since_includes_a_run_started_exactly_at_since(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    blocked = _run(repo, hours=24, status=ScrapeStatus.BLOCKED)

    assert repo.latest_blocked_since(SiteKey.mockshop, T0 + timedelta(hours=24)) is blocked
    assert (
        repo.latest_blocked_since(
            SiteKey.mockshop, T0 + timedelta(hours=24) + timedelta(microseconds=1)
        )
        is None
    )


def test_list_recent_with_zero_limit_is_empty(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    _run(repo)

    assert repo.list_recent(limit=0) == []
