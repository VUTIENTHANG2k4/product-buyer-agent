"""ScrapeService (app/services/scrape_service.py) và script scripts/scrape.py."""

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pytest
from sqlmodel import Session, select

from app.config import Settings
from app.db.models import Offer, PriceHistory, ScrapeRun
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import ChallengeFailed, OfflineMode
from app.scrapers import registry
from app.scrapers.pipeline import ScrapePipeline
from app.services.scrape_service import ScrapeService
from scripts.scrape import (
    EXIT_FAILED,
    EXIT_NEEDS_HUMAN,
    EXIT_OK,
    MAX_ANSWER_ATTEMPTS,
    main,
    run_command,
)
from tests.integration.test_pipeline import (
    Clock,
    RealScraper,
    ScriptedFetcher,
    mock_fetcher,
)

SETTINGS = Settings(scraper_offline_only=True, scraper_max_listing_pages=5)
PriceHook = Callable[[Sequence[int]], Awaitable[None]]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def service(
    factory: Callable[[], Session],
    fetcher: Any,
    clock: Clock,
    *,
    hook: PriceHook | None = None,
) -> ScrapeService:
    pipe = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)
    return ScrapeService(factory, fetcher, SETTINGS, on_price_changes=hook, pipeline=pipe)


# --- ScrapeService ----------------------------------------------------------------------------


async def test_real_sites_are_refused_in_offline_mode_before_any_run_is_created(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(registry.SCRAPERS, SiteKey.gearvn, RealScraper)
    fetcher = ScriptedFetcher({})

    with pytest.raises(OfflineMode) as error:
        await service(factory, fetcher, clock).run(SiteKey.gearvn, Category.laptop)

    assert error.value.details == {"site": "gearvn"}
    assert fetcher.requested == []
    assert db_session.exec(select(ScrapeRun)).all() == []


async def test_run_uses_the_manual_trigger_by_default_and_returns_the_result(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    result = await service(factory, mock_fetcher(), clock).run(SiteKey.mockshop, Category.mouse)

    assert result.status is ScrapeStatus.SUCCEEDED
    db_session.expire_all()
    run = db_session.get(ScrapeRun, result.run_id)
    assert run is not None and run.trigger is ScrapeTrigger.manual


async def test_price_changes_are_handed_to_the_alert_hook(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    calls: list[tuple[int, ...]] = []

    async def hook(ids: Sequence[int]) -> None:
        calls.append(tuple(ids))

    svc = service(factory, mock_fetcher(), clock, hook=hook)
    await svc.run(SiteKey.mockshop, Category.mouse)
    assert calls == []  # lượt đầu: chưa có giá cũ nên chưa có "đổi giá"
    offer = db_session.exec(select(Offer)).first()
    assert offer is not None and offer.id is not None
    row = db_session.exec(select(PriceHistory).where(PriceHistory.offer_id == offer.id)).one()
    row.price += 50_000
    db_session.flush()

    result = await svc.run(SiteKey.mockshop, Category.mouse)

    assert calls == [(offer.id,)]
    assert result.changed_offer_ids == (offer.id,)


async def test_a_failing_alert_hook_does_not_lose_the_scrape_result(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def hook(ids: Sequence[int]) -> None:
        raise RuntimeError("smtp down")

    svc = service(factory, mock_fetcher(), clock, hook=hook)
    await svc.run(SiteKey.mockshop, Category.mouse)
    row = db_session.exec(select(PriceHistory)).first()
    assert row is not None
    row.price += 1
    db_session.flush()

    result = await svc.run(SiteKey.mockshop, Category.mouse)

    assert result.status is ScrapeStatus.SUCCEEDED and result.price_changes == 1
    assert "đánh giá cảnh báo giá thất bại" in caplog.text


async def test_resume_is_forwarded_and_wrong_answers_raise(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, mock_fetcher(captcha_after=1), clock)
    paused = await svc.run(SiteKey.mockshop, Category.laptop)
    assert paused.challenge is not None and paused.challenge.prompt is not None

    with pytest.raises(ChallengeFailed):
        await svc.resume(paused.run_id, "WRONG")
    code = re.search(r"[A-Z2-9]{5}$", paused.challenge.prompt)
    assert code
    done = await svc.resume(paused.run_id, code.group(0))
    assert done.status is ScrapeStatus.SUCCEEDED


# --- scripts/scrape.py ------------------------------------------------------------------------


async def command(
    svc: ScrapeService,
    *,
    site: SiteKey = SiteKey.mockshop,
    category: Category = Category.mouse,
    pages: int | None = None,
    resume_run: int | None = None,
    answer: str | None = None,
    ask: Callable[[str], str] | None = None,
) -> int:
    return await run_command(
        svc,
        site=site,
        category=category,
        pages=pages,
        resume_run=resume_run,
        answer=answer,
        ask=ask,
    )


async def test_script_returns_ok_for_a_clean_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    assert await command(service(factory, mock_fetcher(), clock)) == EXIT_OK


async def test_script_passes_the_page_limit_through_and_partial_still_exits_ok(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    code = await command(service(factory, mock_fetcher(), clock), category=Category.laptop, pages=1)

    assert code == EXIT_OK  # PARTIAL: dữ liệu đã lưu
    db_session.expire_all()
    run = db_session.exec(select(ScrapeRun)).one()
    assert (run.status, run.pages_fetched) == (ScrapeStatus.PARTIAL, 1)


async def test_script_asks_for_the_answer_on_a_terminal_and_finishes_the_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        match = re.search(r"([A-Z2-9]{5})\n", prompt)
        assert match
        return match.group(1)

    code = await command(
        service(factory, mock_fetcher(captcha_after=1), clock), category=Category.laptop, ask=ask
    )

    assert code == EXIT_OK
    assert len(prompts) == 1 and prompts[0].endswith("\n> ")
    db_session.expire_all()
    assert db_session.exec(select(ScrapeRun)).one().status is ScrapeStatus.SUCCEEDED


async def test_script_gives_up_after_three_wrong_answers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    answers: list[str] = []

    def ask(prompt: str) -> str:
        answers.append("ZZZZZ")
        return "ZZZZZ"

    code = await command(
        service(factory, mock_fetcher(captcha_after=1), clock), category=Category.laptop, ask=ask
    )

    assert code == EXIT_NEEDS_HUMAN
    assert len(answers) == MAX_ANSWER_ATTEMPTS
    db_session.expire_all()
    assert db_session.exec(select(ScrapeRun)).one().status is ScrapeStatus.NEEDS_HUMAN


async def test_script_without_a_terminal_exits_3_and_the_run_can_be_resumed_later(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    svc = service(factory, mock_fetcher(captcha_after=1), clock)

    code = await command(svc, category=Category.laptop, ask=None)

    assert code == EXIT_NEEDS_HUMAN
    db_session.expire_all()
    run = db_session.exec(select(ScrapeRun)).one()
    assert run.id is not None and run.challenge is not None
    assert f"--resume {run.id}" in caplog.text
    match = re.search(r"[A-Z2-9]{5}$", str(run.challenge["prompt"]))
    assert match

    resumed = await command(svc, category=Category.laptop, resume_run=run.id, answer=match.group(0))
    assert resumed == EXIT_OK


async def test_script_reports_domain_errors_as_exit_1(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, mock_fetcher(), clock)
    assert await command(svc, site=SiteKey.viettelstore) == EXIT_FAILED  # chưa đăng ký
    assert await command(svc, resume_run=999_999, answer="ABCDE") == EXIT_FAILED  # không có lượt


async def test_script_exit_code_is_1_when_the_run_fails(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({"http://localhost:8100/c/mouse": RuntimeError("x")})
    assert await command(service(factory, fetcher, clock)) == EXIT_FAILED


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--site", "mockshop"],
        ["--site", "nope", "--category", "laptop"],
        ["--site", "mockshop", "--category", "laptop", "--pages", "0"],
        ["--site", "mockshop", "--category", "laptop", "--resume", "3"],
    ],
)
def test_script_rejects_bad_arguments_with_usage_error(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_console_is_switched_to_utf8_so_vietnamese_prompts_do_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import sys

    from scripts.scrape import configure_console

    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", stdout)
    with pytest.raises(UnicodeEncodeError):
        stdout.write("Nhập mã")  # tái hiện lỗi gặp khi chạy thật

    configure_console()
    stdout.write("Nhập mã xác minh")

    assert raw.getvalue().decode("utf-8").endswith("Nhập mã xác minh")
