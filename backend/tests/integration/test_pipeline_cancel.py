"""T2.8: hủy lượt `NEEDS_HUMAN` để lượt mới chạy ngay."""

from collections.abc import Callable

import pytest
from sqlmodel import Session

from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import ChallengeNotPending, RunNotFound
from app.scrapers.pipeline import CANCELLED_BY_USER, NEEDS_HUMAN_STALE_AFTER
from tests.integration.test_pipeline import Clock, mock_fetcher, pipeline, run_row


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


async def test_cancelling_a_paused_run_closes_it_as_failed_and_frees_the_slot(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert paused.status is ScrapeStatus.NEEDS_HUMAN

    await pipe.cancel_paused(paused.run_id)

    run = run_row(db_session, paused)
    assert run.status is ScrapeStatus.FAILED and run.challenge is None
    assert run.error_message == CANCELLED_BY_USER and run.finished_at == clock.now
    # Lượt mới chạy được ngay (không phải chờ 1 giờ, không ScrapeAlreadyRunning).
    again = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert again.run_id != paused.run_id and again.status is ScrapeStatus.NEEDS_HUMAN


async def test_a_cancelled_run_cannot_be_answered_or_cancelled_again(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    await pipe.cancel_paused(paused.run_id)

    with pytest.raises(ChallengeNotPending) as again:
        await pipe.cancel_paused(paused.run_id)
    with pytest.raises(ChallengeNotPending):
        await pipe.resume(paused.run_id, "ABCDE")

    assert again.value.details["status"] == "FAILED"


async def test_cancelling_unknown_and_finished_runs_is_refused(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    done = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    with pytest.raises(RunNotFound):
        await pipe.cancel_paused(999_999)
    with pytest.raises(ChallengeNotPending) as error:
        await pipe.cancel_paused(done.run_id)

    assert error.value.details["status"] == "SUCCEEDED"
    assert run_row(db_session, done).status is ScrapeStatus.SUCCEEDED  # không đổi


async def test_a_stale_paused_run_can_still_be_cancelled_to_clean_up(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    clock.now = clock.now + NEEDS_HUMAN_STALE_AFTER * 2

    await pipe.cancel_paused(paused.run_id)

    assert run_row(db_session, paused).status is ScrapeStatus.FAILED
