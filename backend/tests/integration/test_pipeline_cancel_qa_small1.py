"""QA small-1: biên của `ScrapePipeline.cancel_paused` (T2.8) trên PostgreSQL thật."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app.db.models import Offer, ScrapeRun
from app.db.repositories import ScrapeRunRepository
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import ChallengeNotPending, RunNotFound
from app.scrapers.pipeline import CANCELLED_BY_USER, NEEDS_HUMAN_STALE_AFTER
from tests.integration.test_pipeline import NOW, Clock, mock_fetcher, pipeline

CHALLENGE: dict[str, object] = {
    "kind": "captcha",
    "prompt": "Nhập mã: ABCDE",
    "token": "t",
    "image_url": None,
}


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def add_run(
    session: Session,
    status: ScrapeStatus,
    *,
    category: Category = Category.laptop,
    trigger: ScrapeTrigger = ScrapeTrigger.test,
    challenge: dict[str, object] | None = None,
) -> int:
    repo = ScrapeRunRepository(session)
    run = repo.create(SiteKey.mockshop, category, trigger, now=NOW)
    repo.set_status(run, status, challenge=challenge, error_message="giữ nguyên", now=NOW)
    session.commit()
    assert run.id is not None
    return run.id


def reload(session: Session, run_id: int) -> ScrapeRun:
    session.expire_all()
    run = session.get(ScrapeRun, run_id)
    assert run is not None
    return run


@pytest.mark.parametrize(
    "status",
    [
        ScrapeStatus.PENDING,
        ScrapeStatus.RUNNING,
        ScrapeStatus.SUCCEEDED,
        ScrapeStatus.FAILED,
        ScrapeStatus.BLOCKED,
        ScrapeStatus.PARTIAL,
    ],
)
async def test_every_status_except_needs_human_is_refused_and_left_untouched(
    db_session: Session, factory: Callable[[], Session], clock: Clock, status: ScrapeStatus
) -> None:
    run_id = add_run(db_session, status)
    before = reload(db_session, run_id)
    snapshot = (before.status, before.error_message, before.finished_at, before.challenge)
    pipe = pipeline(factory, mock_fetcher(), clock)

    with pytest.raises(ChallengeNotPending) as error:
        await pipe.cancel_paused(run_id)

    assert error.value.status_code == 409
    assert error.value.details == {"run_id": run_id, "status": status.value}
    after = reload(db_session, run_id)
    assert (after.status, after.error_message, after.finished_at, after.challenge) == snapshot


@pytest.mark.parametrize("run_id", [0, -1, -(2**31), 2**31, 2**31 + 1, 2**63, 2**64, 10**30])
async def test_run_ids_outside_the_primary_key_domain_are_not_found_not_a_database_error(
    factory: Callable[[], Session], clock: Clock, run_id: int
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)

    with pytest.raises(RunNotFound):
        await pipe.cancel_paused(run_id)


async def test_a_tracked_refresh_run_stuck_in_needs_human_can_be_cancelled_for_cleanup(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    """`resume` từ chối lượt này (không có trang danh sách), nên hủy là cách dọn duy nhất."""
    run_id = add_run(
        db_session,
        ScrapeStatus.NEEDS_HUMAN,
        trigger=ScrapeTrigger.tracked_refresh,
        challenge=CHALLENGE,
    )
    pipe = pipeline(factory, mock_fetcher(), clock)
    with pytest.raises(ChallengeNotPending):
        await pipe.resume(run_id, "ABCDE")

    await pipe.cancel_paused(run_id)

    run = reload(db_session, run_id)
    assert run.status is ScrapeStatus.FAILED and run.error_message == CANCELLED_BY_USER


async def test_a_needs_human_run_with_a_lost_challenge_can_still_be_cancelled(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    run_id = add_run(db_session, ScrapeStatus.NEEDS_HUMAN, challenge=None)
    pipe = pipeline(factory, mock_fetcher(), clock)

    await pipe.cancel_paused(run_id)

    run = reload(db_session, run_id)
    assert run.status is ScrapeStatus.FAILED and run.challenge is None
    assert run.finished_at == clock.now


async def test_cancelling_leaves_the_other_runs_of_the_same_and_other_groups_alone(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    old = add_run(db_session, ScrapeStatus.NEEDS_HUMAN, challenge=CHALLENGE)
    clock.now = NOW + NEEDS_HUMAN_STALE_AFTER + timedelta(minutes=1)
    newer = add_run(db_session, ScrapeStatus.PENDING)
    elsewhere = add_run(
        db_session, ScrapeStatus.NEEDS_HUMAN, category=Category.mouse, challenge=CHALLENGE
    )
    pipe = pipeline(factory, mock_fetcher(), clock)

    await pipe.cancel_paused(old)

    assert reload(db_session, old).status is ScrapeStatus.FAILED
    assert reload(db_session, newer).status is ScrapeStatus.PENDING
    elsewhere_run = reload(db_session, elsewhere)
    assert elsewhere_run.status is ScrapeStatus.NEEDS_HUMAN and elsewhere_run.challenge is not None


async def test_cancelled_run_does_not_touch_offers_and_the_next_run_succeeds(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    db_session.expire_all()
    offers_before = len(db_session.exec(select(Offer)).all())

    await pipe.cancel_paused(paused.run_id)

    db_session.expire_all()
    assert len(db_session.exec(select(Offer)).all()) == offers_before
    fresh = pipeline(factory, mock_fetcher(), clock)
    again = await fresh.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert again.status is ScrapeStatus.SUCCEEDED and again.run_id != paused.run_id
    assert reload(db_session, paused.run_id).status is ScrapeStatus.FAILED


async def test_a_cancelled_run_is_closed_as_failed_with_no_challenge_left(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    await pipe.cancel_paused(paused.run_id)

    run = reload(db_session, paused.run_id)
    assert run.status is ScrapeStatus.FAILED
    assert run.challenge is None and run.finished_at is not None
