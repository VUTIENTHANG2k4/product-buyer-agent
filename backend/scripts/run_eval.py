"""Chạy eval agent với LLM thật trên docs/eval/queries.yaml (docs/05 §7, T6.6).

Chạy từ `backend/`: `uv run python -m scripts.run_eval [--cases L01,C02] [--sleep 6]`
(`make eval`, `make eval CASES="L01 C02"`). Cần `LLM_PROVIDER=gemini|openai` kèm khóa API trong
`.env` và `TEST_DATABASE_URL` (DB kết thúc `_test`, đã `make db-up`).

Dữ liệu: seed `eval` (hư cấu) được nạp trong MỘT transaction trên DB test rồi hoàn tác khi chạy
xong, nên eval luôn chạy trên dữ liệu cố định và không đụng DB dev (dữ liệu thu thập thật). Đừng
chạy cùng lúc với `pytest` (hai bên cùng nạp seed, sẽ chờ khóa của nhau).

Báo cáo ghi ra `reports/eval-<ngày>.md` (`-partial` nếu chỉ chạy một số câu). Mã thoát: 0 khi mọi
chỉ số đạt ngưỡng, 1 khi có chỉ số dưới ngưỡng, 2 khi không chạy được.
"""

import argparse
import asyncio
import logging
import sys
import time
import warnings
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Final

import httpx
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.agent.guardrail import GuardrailOutcome
from app.agent.llm import get_chat_model
from app.agent.runner import AgentRunner
from app.agent.schemas import ClarificationEvent, ErrorEvent, FinalEvent, PlanEvent, ToolStartEvent
from app.config import Settings, get_settings
from app.db.models import utc_now
from app.domain.errors import AppError
from app.mock_shop.main import create_app
from app.scrapers.http.types import FetchResponse
from app.services.catalog_service import CatalogService
from app.services.live_search_service import LiveSearchService
from scripts.eval_core import (
    CaseRun,
    EvalCase,
    ProductFacts,
    all_thresholds_met,
    compute_metrics,
    load_cases,
    render_report,
    report_path,
    score_case,
)
from scripts.scrape import configure_console
from scripts.seed import seed_database
from tests.db_support import upgrade_to_head

logger = logging.getLogger("eval")

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_SETUP = 0, 1, 2
DEFAULT_RPM: Final = 12  # dưới hạn mức 15 request/phút của gói miễn phí Gemini

FactsOf = Callable[[list[int]], list[ProductFacts]]


class MockShopFetcher:
    """PageFetcher gọi mock-shop trong tiến trình qua ASGI (không mạng, không cần `make mock-shop`).

    Eval tầng 2 dùng cái này để kết quả tìm trực tiếp không phụ thuộc trang thật.
    """

    def __init__(self) -> None:
        self._transport = httpx.ASGITransport(app=create_app(captcha_after=10**6))

    async def get(self, url: str) -> FetchResponse:
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.get(url)
        return FetchResponse(
            url=url, final_url=str(response.url), status=response.status_code, text=response.text
        )


class SetupError(Exception):
    """Cấu hình thiếu hoặc không an toàn để chạy eval (mã thoát 2)."""


async def run_case(
    case: EvalCase, runner: AgentRunner, guard: list[GuardrailOutcome], facts_of: FactsOf
) -> CaseRun:
    """Chạy các lượt `context` rồi câu hỏi chính trong cùng một hội thoại và ghi lại quan sát.

    `guard` là danh sách mà `runner.observer` thêm kết quả guardrail vào; chỉ lượt chính được tính.
    """
    run = CaseRun()
    try:
        conversation_id: int | None = None
        for text in case.context:
            handle = await runner.start(text, conversation_id)
            conversation_id = handle.conversation_id
            async for _ in runner.stream(handle, text):
                pass
        guard.clear()
        started = time.perf_counter()
        handle = await runner.start(case.query, conversation_id)
        product_ids: list[int] = []
        async for event in runner.stream(handle, case.query):
            if isinstance(event, PlanEvent):
                run.intent = event.intent.model_dump(mode="json")
            elif isinstance(event, ToolStartEvent):
                run.tools_called.append(event.tool)
            elif isinstance(event, ClarificationEvent):
                run.clarification = event.question
            elif isinstance(event, FinalEvent):
                run.final_text = event.text
                product_ids = [row.product_id for row in event.table]
            elif isinstance(event, ErrorEvent):
                run.error_code = event.code
        run.latency_s = time.perf_counter() - started
        run.products = facts_of(product_ids)
        if guard:
            verdict = guard[-1]
            run.dropped_product_ids = list(verdict.dropped_product_ids)
            run.dropped_live_urls = [*verdict.dropped_live_urls, *verdict.dropped_text_urls]
            run.price_warnings = list(verdict.price_warnings)
    except Exception as error:
        run.crashed = f"{type(error).__name__}: {error}"
    return run


def make_facts_of(factory: Callable[[], Session]) -> FactsOf:
    """Đọc brand, giá thấp nhất, trang bán và specs của sản phẩm trong bảng kết quả."""

    def facts_of(product_ids: list[int]) -> list[ProductFacts]:
        if not product_ids:
            return []
        with factory() as session:
            products = CatalogService(session).get_many(product_ids)
            return [
                ProductFacts(
                    product_id=p.product_id,
                    brand=p.brand,
                    min_price=p.min_price,
                    sites=frozenset(offer.site.value for offer in p.offers),
                    specs=p.specs,
                )
                for p in products
            ]

    return facts_of


def _test_engine(settings: Settings) -> Engine:
    url = make_url(settings.test_database_url.get_secret_value())
    if not (url.database or "").endswith("_test"):
        raise SetupError(
            "TEST_DATABASE_URL phải trỏ tới DB có tên kết thúc bằng _test "
            f"(nhận {url.database!r}); eval không chạy trên DB dev."
        )
    if url.host == "localhost":  # Windows: localhost thử IPv6 trước và treo mỗi kết nối mới
        url = url.set(host="127.0.0.1")
    return create_engine(url, connect_args={"connect_timeout": 3})


async def run_all(
    cases: Sequence[EvalCase],
    runner: AgentRunner,
    guard: list[GuardrailOutcome],
    facts_of: FactsOf,
    *,
    pause_s: float = 0.0,
    report: Callable[[str], None] = print,
) -> list[CaseRun]:
    runs: list[CaseRun] = []
    for index, case in enumerate(cases, 1):
        run = await run_case(case, runner, guard, facts_of)
        runs.append(run)
        score = score_case(case, run)
        report(
            f"[{index}/{len(cases)}] {case.id} {'PASS' if score.passed else 'FAIL'} "
            f"tools={run.tools_called} kết quả={len(run.products)} "
            f"{'' if run.latency_s is None else f'{run.latency_s:.1f}s'}"
            + (f" lỗi={run.error_code or run.crashed}" if run.error_code or run.crashed else "")
        )
        if pause_s and index < len(cases):
            await asyncio.sleep(pause_s)
    return runs


def _parse_ids(values: Sequence[str]) -> list[str]:
    return [part for value in values for part in value.replace(",", " ").split()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eval agent với LLM thật (docs/05 §7).")
    parser.add_argument(
        "--cases", nargs="*", default=[], help="id câu hỏi (cách nhau bởi , hoặc dấu cách)"
    )
    parser.add_argument(
        "--sleep", type=float, default=0.0, help="giây nghỉ giữa hai câu (tránh giới hạn tốc độ)"
    )
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "reports")
    parser.add_argument(
        "--rpm",
        type=int,
        help=f"số lần gọi LLM tối đa mỗi phút (mặc định LLM_MAX_RPM, nếu 0 thì {DEFAULT_RPM})",
    )
    args = parser.parse_args(argv)
    configure_console()
    # Gemini ghi cảnh báo mỗi lần bỏ qua `additionalProperties` trong schema (không phải lỗi).
    logging.getLogger("langchain_google_genai").setLevel(logging.ERROR)

    settings = get_settings()
    rpm = args.rpm if args.rpm is not None else (settings.llm_max_rpm or DEFAULT_RPM)
    # Địa chỉ nhận cảnh báo giả để câu "báo tôi khi…" chạy được mà không phụ thuộc .env của máy.
    settings = settings.model_copy(
        update={
            "llm_max_rpm": max(0, rpm),
            "alert_default_email": settings.alert_default_email or "eval@example.com",
        }
    )
    warnings.filterwarnings("ignore", message=".*fixed sampling defaults.*")
    if settings.llm_provider == "fake":
        logger.error(
            "Eval cần LLM thật: đặt LLM_PROVIDER=gemini (hoặc openai) và khóa API trong .env."
        )
        return EXIT_SETUP
    if not settings.test_database_url.get_secret_value():
        logger.error("Thiếu TEST_DATABASE_URL trong .env (DB test, tên kết thúc _test).")
        return EXIT_SETUP
    try:
        cases = load_cases(only=_parse_ids(args.cases))
        planner_model = get_chat_model("planner", settings)
        executor_model = get_chat_model("executor", settings)
    except (ValueError, AppError) as error:
        logger.error("Không chạy được: %s", getattr(error, "message", None) or error)
        return EXIT_SETUP

    try:
        engine = _test_engine(settings)
        upgrade_to_head(engine)
        connection = engine.connect()
    except SetupError as error:
        logger.error("%s", error)
        return EXIT_SETUP
    except OperationalError:
        logger.error("Không kết nối được DB test. Chạy `make db-up` và kiểm tra TEST_DATABASE_URL.")
        return EXIT_SETUP

    transaction = connection.begin()
    try:

        def factory() -> Session:
            return Session(bind=connection, join_transaction_mode="create_savepoint")

        with factory() as session:
            seed_database(session, "eval", now=utc_now())
            session.commit()
        guard: list[GuardrailOutcome] = []
        runner = AgentRunner(
            factory,
            settings,
            planner_model=planner_model,
            executor_model=executor_model,
            observer=guard.append,
            live_search=LiveSearchService(
                factory,
                settings.model_copy(update={"scraper_offline_only": True}),
                MockShopFetcher(),
            ),
        )
        logger.info("Chạy %d câu với %s", len(cases), settings.llm_provider)
        runs = asyncio.run(
            run_all(
                cases, runner, guard, make_facts_of(factory), pause_s=args.sleep, report=logger.info
            )
        )
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()

    if runs and all(run.crashed for run in runs):  # môi trường hỏng, không phải agent kém
        logger.error("Mọi %d ca đều lỗi ngoài dự kiến (ca đầu: %s)", len(runs), runs[0].crashed)
        return EXIT_SETUP
    scores = [score_case(case, run) for case, run in zip(cases, runs, strict=True)]
    metrics = compute_metrics(scores)
    partial = bool(args.cases)
    model = settings.gemini_model if settings.llm_provider == "gemini" else settings.openai_model
    today = date.today()
    text = render_report(
        scores,
        metrics,
        today=today,
        provider=settings.llm_provider,
        model=model,
        partial=partial,
        rpm=settings.llm_max_rpm,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = report_path(args.output_dir, today, partial=partial)
    path.write_text(text, encoding="utf-8", newline="\n")
    for metric in metrics:
        status = {True: "đạt", False: "CHƯA ĐẠT", None: "không có ca"}[metric.ok]
        logger.info("%-26s %-8s %s (%s)", metric.label, f"{metric.value}", status, metric.detail)
    logger.info("Báo cáo: %s", path)
    return EXIT_OK if all_thresholds_met(metrics) else EXIT_BELOW_THRESHOLD


if __name__ == "__main__":
    sys.exit(main())
