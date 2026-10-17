from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.db.repositories.scrape_runs import ScrapeRunRepository
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _create(
    repo: ScrapeRunRepository,
    *,
    site: SiteKey = SiteKey.mockshop,
    category: Category = Category.laptop,
    status: ScrapeStatus = ScrapeStatus.RUNNING,
    hours: int = 0,
) -> int:
    run = repo.create(
        site, category, ScrapeTrigger.test, status=status, now=T0 + timedelta(hours=hours)
    )
    assert run.id is not None
    return run.id


def test_create_starts_running_with_zero_counters(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)

    run = repo.create(SiteKey.gearvn, Category.mouse, ScrapeTrigger.manual, now=T0)

    assert run.id is not None
    assert (run.site, run.category, run.trigger) == (
        SiteKey.gearvn,
        Category.mouse,
        ScrapeTrigger.manual,
    )
    assert run.status == ScrapeStatus.RUNNING
    assert run.started_at == T0
    assert run.finished_at is None
    assert (run.pages_fetched, run.items_parsed, run.items_failed) == (0, 0, 0)
    assert (run.offers_upserted, run.price_changes) == (0, 0)
    assert repo.get(run.id) is run
    assert repo.get(999_999_999) is None


def test_update_counters_sets_only_the_given_counters(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    run = repo.create(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    repo.update_counters(run, pages_fetched=3, items_parsed=60)
    repo.update_counters(run, items_failed=2, offers_upserted=58, price_changes=5)
    repo.update_counters(run)
    db_session.expire(run)

    assert (run.pages_fetched, run.items_parsed, run.items_failed) == (3, 60, 2)
    assert (run.offers_upserted, run.price_changes) == (58, 5)


def test_set_status_terminal_sets_finished_at_and_error(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    run = repo.create(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=T0)

    repo.set_status(run, ScrapeStatus.FAILED, error_message="boom", now=T0 + timedelta(minutes=2))

    assert run.status == ScrapeStatus.FAILED
    assert run.error_message == "boom"
    assert run.finished_at == T0 + timedelta(minutes=2)


def test_needs_human_keeps_challenge_and_stays_unfinished_then_resumes(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    run = repo.create(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=T0)
    challenge = {"kind": "captcha", "image_url": "http://mock/captcha.png"}

    repo.set_status(run, ScrapeStatus.NEEDS_HUMAN, challenge=challenge)
    db_session.expire(run)
    assert run.status == ScrapeStatus.NEEDS_HUMAN
    assert run.challenge == challenge
    assert run.finished_at is None

    repo.set_status(run, ScrapeStatus.RUNNING)
    repo.set_status(run, ScrapeStatus.SUCCEEDED, now=T0 + timedelta(minutes=5))
    db_session.expire(run)
    assert run.challenge is None
    assert run.finished_at == T0 + timedelta(minutes=5)


def test_resuming_a_finished_run_clears_finished_at(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    run = repo.create(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=T0)
    repo.set_status(run, ScrapeStatus.PARTIAL, now=T0 + timedelta(minutes=1))

    repo.set_status(run, ScrapeStatus.RUNNING)

    assert run.finished_at is None


def test_latest_picks_newest_for_the_site_and_category(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    old = _create(repo, hours=0)
    new = _create(repo, hours=2)
    _create(repo, category=Category.mouse, hours=5)
    _create(repo, site=SiteKey.gearvn, hours=6)

    latest = repo.latest(SiteKey.mockshop, Category.laptop)

    assert latest is not None and latest.id == new
    assert old != new
    assert repo.latest(SiteKey.hoangha, Category.laptop) is None


def test_latest_succeeded_skips_other_statuses(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    good = _create(repo, status=ScrapeStatus.SUCCEEDED, hours=0)
    _create(repo, status=ScrapeStatus.FAILED, hours=1)
    _create(repo, status=ScrapeStatus.PARTIAL, hours=2)

    latest = repo.latest_succeeded(SiteKey.mockshop, Category.laptop)

    assert latest is not None and latest.id == good
    assert repo.latest_succeeded(SiteKey.mockshop, Category.mouse) is None


def test_list_recent_orders_newest_first_filters_by_site_and_limits(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    first = _create(repo, hours=0)
    second = _create(repo, site=SiteKey.gearvn, hours=1)
    third = _create(repo, hours=2)

    assert [run.id for run in repo.list_recent()] == [third, second, first]
    assert [run.id for run in repo.list_recent(site=SiteKey.mockshop)] == [third, first]
    assert [run.id for run in repo.list_recent(limit=1)] == [third]


def test_latest_blocked_since_respects_site_status_and_window(db_session: Session) -> None:
    repo = ScrapeRunRepository(db_session)
    _create(repo, site=SiteKey.gearvn, status=ScrapeStatus.BLOCKED, hours=0)
    recent = _create(repo, site=SiteKey.gearvn, status=ScrapeStatus.BLOCKED, hours=30)
    _create(repo, site=SiteKey.gearvn, status=ScrapeStatus.FAILED, hours=40)
    _create(repo, site=SiteKey.hoangha, status=ScrapeStatus.BLOCKED, hours=41)
    since = T0 + timedelta(hours=24)

    blocked = repo.latest_blocked_since(SiteKey.gearvn, since)

    assert blocked is not None and blocked.id == recent
    assert repo.latest_blocked_since(SiteKey.gearvn, T0 + timedelta(hours=31)) is None
    assert repo.latest_blocked_since(SiteKey.laptop88, since) is None
