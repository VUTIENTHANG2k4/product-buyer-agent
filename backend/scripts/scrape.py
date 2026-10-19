"""Chạy một lượt thu thập từ dòng lệnh (docs/06 §9, T2.6).

Chạy từ `backend/`: `uv run python -m scripts.scrape --site mockshop --category laptop [--pages N]`
(`make scrape SITE=mockshop CAT=laptop`). Cần PostgreSQL đã migrate và mock-shop đang chạy
(`make mock-shop`). Gặp captcha của mock-shop, lệnh hỏi đáp án trên terminal; không có terminal
thì in lệnh `--resume RUN_ID --answer MÃ` để tiếp tục. Trang thật chỉ chạy khi người dùng tự đặt
`SCRAPER_OFFLINE_ONLY=false`; script không đổi cấu hình này.
"""

import argparse
import asyncio
import io
import logging
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.config import get_settings
from app.db.engine import get_engine
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import AppError
from app.scrapers.http.errors import FetchError
from app.scrapers.http.factory import build_fetcher
from app.scrapers.pipeline import PipelineResult
from app.scrapers.registry import SiteNotAvailable
from app.services.scrape_service import ScrapeService

logger = logging.getLogger("scrape")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NEEDS_HUMAN = 3
MAX_ANSWER_ATTEMPTS = 3


def _log_result(result: PipelineResult) -> None:
    logger.info(
        "Lượt %s: %s | %s trang, %s mục (%s lỗi), %s offer, %s đổi giá",
        result.run_id,
        result.status.value,
        result.pages_fetched,
        result.items_parsed,
        result.items_failed,
        result.offers_upserted,
        result.price_changes,
    )
    if result.error_message:
        logger.warning("%s", result.error_message)


def _exit_code(result: PipelineResult) -> int:
    if result.status is ScrapeStatus.NEEDS_HUMAN:
        return EXIT_NEEDS_HUMAN
    if result.status in (ScrapeStatus.SUCCEEDED, ScrapeStatus.PARTIAL):
        return EXIT_OK
    return EXIT_FAILED


async def drive(
    service: ScrapeService,
    result: PipelineResult,
    ask: Callable[[str], str] | None,
    *,
    pages: int | None,
) -> PipelineResult:
    """Hỏi đáp án (tối đa 3 lần) khi lượt chờ người; `ask=None` nghĩa là không có terminal."""
    attempts = 0
    while result.status is ScrapeStatus.NEEDS_HUMAN and ask is not None:
        if attempts >= MAX_ANSWER_ATTEMPTS:
            break
        challenge = result.challenge
        prompt = (challenge.prompt if challenge else None) or "Nhập đáp án"
        answer = ask(f"{prompt}\n> ").strip()
        attempts += 1
        try:
            result = await service.resume(result.run_id, answer, max_pages=pages)
        except AppError as error:
            logger.warning("%s", error.message)
            continue
        _log_result(result)
    return result


async def run_command(
    service: ScrapeService,
    *,
    site: SiteKey,
    category: Category,
    pages: int | None,
    resume_run: int | None,
    answer: str | None,
    ask: Callable[[str], str] | None,
) -> int:
    try:
        if resume_run is not None:
            result = await service.resume(resume_run, answer or "", max_pages=pages)
        else:
            result = await service.run(
                site, category, trigger=ScrapeTrigger.manual, max_pages=pages
            )
    except (AppError, SiteNotAvailable, FetchError) as error:
        logger.error("Không chạy được: %s", getattr(error, "message", None) or error)
        return EXIT_FAILED
    _log_result(result)
    result = await drive(service, result, ask, pages=pages)
    if result.status is ScrapeStatus.NEEDS_HUMAN:
        logger.warning(
            "Lượt %s đang chờ đáp án. Tiếp tục: uv run python -m scripts.scrape --site %s "
            "--category %s --resume %s --answer MÃ",
            result.run_id,
            site.value,
            category.value,
            result.run_id,
        )
    return _exit_code(result)


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = get_engine(settings.database_url.get_secret_value())
    ask: Callable[[str], str] | None = input if sys.stdin.isatty() else None
    async with build_fetcher(settings) as fetcher:
        service = ScrapeService(lambda: Session(engine), fetcher, settings)
        return await run_command(
            service,
            site=args.site,
            category=args.category,
            pages=args.pages,
            resume_run=args.resume,
            answer=args.answer,
            ask=ask,
        )


def configure_console() -> None:
    """UTF-8 cho stdout/stderr và log gọn. Console Windows hoặc pipe mặc định cp1252 nên lời nhắc
    tiếng Việt của `input()` (đề bài captcha) sẽ ném `UnicodeEncodeError` nếu không đổi."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chạy một lượt thu thập (docs/06 §9).")
    parser.add_argument("--site", type=SiteKey, choices=list(SiteKey), required=True)
    parser.add_argument("--category", type=Category, choices=list(Category), required=True)
    parser.add_argument("--pages", type=int, help="số trang danh sách tối đa (mặc định theo .env)")
    parser.add_argument(
        "--resume", type=int, metavar="RUN_ID", help="tiếp tục lượt đang chờ đáp án"
    )
    parser.add_argument("--answer", help="đáp án captcha của mock-shop (dùng với --resume)")
    args = parser.parse_args(argv)
    if args.pages is not None and args.pages < 1:
        parser.error("--pages phải >= 1")
    if args.resume is not None and not args.answer:
        parser.error("--resume cần --answer")
    configure_console()
    try:
        return asyncio.run(_main(args))
    except OperationalError:
        logger.error("Không kết nối được CSDL. Chạy `make db-up` và kiểm tra DATABASE_URL.")
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
