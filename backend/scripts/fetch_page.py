"""Lưu một trang qua Fetcher để làm fixture (docs/06 §8).

Chạy từ `backend/`: `uv run python -m scripts.fetch_page --site mockshop --url <url> --out <file>`.
Mọi request đi qua Fetcher (robots.txt, độ trễ, User-Agent trung thực). Với trang thật khi
`SCRAPER_OFFLINE_ONLY=true`, cờ `--allow-online` cho phép đúng lệnh này truy cập trang thật; chỉ
dùng khi người dùng đã đồng ý trong task khảo sát. Không sửa `.env`.
"""

import argparse
import asyncio
import io
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from app.config import get_settings
from app.domain.enums import SiteKey
from app.scrapers.challenge import detect_challenge
from app.scrapers.http.errors import FetchError
from app.scrapers.http.factory import build_fetcher
from app.scrapers.registry import SCRAPERS

logger = logging.getLogger("fetch_page")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2


def _write(out: Path, text: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


async def fetch_to_file(site: SiteKey, url: str, out: Path, *, allow_online: bool) -> int:
    scraper = SCRAPERS.get(site)
    if scraper is None:
        logger.error("Trang %s chưa có scraper đăng ký (app/scrapers/registry.py).", site)
        return EXIT_FAILED
    if urlsplit(url).netloc.lower() != urlsplit(scraper.config.base_url).netloc.lower():
        logger.error("URL phải thuộc %s.", scraper.config.base_url)
        return EXIT_FAILED

    settings = get_settings()
    if allow_online and settings.scraper_offline_only:
        # Chỉ cho tiến trình này; không ghi vào .env.
        settings = settings.model_copy(update={"scraper_offline_only": False})
    async with build_fetcher(settings, raw_cache_dir=None) as fetcher:
        try:
            response = await fetcher.get(url)
        except FetchError as error:
            logger.error("Không tải được trang: %s (%s)", error, type(error).__name__)
            return EXIT_FAILED
    challenge = detect_challenge(response, site)
    if challenge is not None:
        logger.error("Trang trả challenge %s: dừng, không lưu file.", challenge.kind)
        return EXIT_BLOCKED
    try:
        await asyncio.to_thread(_write, out, response.text)
    except OSError as error:
        logger.error("Không ghi được file %s: %s", out, type(error).__name__)
        return EXIT_FAILED
    logger.info("Đã lưu %d ký tự từ %s vào %s", len(response.text), response.final_url, out)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lưu một trang qua Fetcher (docs/06 §8).")
    parser.add_argument("--site", type=SiteKey, choices=list(SiteKey), required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--allow-online",
        action="store_true",
        help="cho phép truy cập trang thật dù SCRAPER_OFFLINE_ONLY=true (chỉ lệnh này)",
    )
    args = parser.parse_args(argv)
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return asyncio.run(fetch_to_file(args.site, args.url, args.out, allow_online=args.allow_online))


if __name__ == "__main__":
    raise SystemExit(main())
