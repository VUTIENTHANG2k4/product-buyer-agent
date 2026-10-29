"""Ghép lại offer đã có theo luật chuẩn hóa hiện tại (T5.4, docs/04 §7).

Chạy từ `backend/`: `uv run python -m scripts.rematch [--category laptop] [--site gearvn] [--apply]`
(hoặc `make rematch [CAT=laptop] [SITE=gearvn] [APPLY=1]`). Mặc định chỉ chạy thử và in điều sẽ đổi;
`--apply` mới ghi vào CSDL (một transaction). Không gọi mạng, không gọi LLM.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Final

from sqlmodel import Session

from app.config import get_settings
from app.db.engine import get_engine
from app.domain.enums import Category, SiteKey
from app.services.rematch_service import REMATCH_CATEGORIES, RematchReport, RematchService
from scripts.scrape import configure_console

MAX_LISTED_MOVES: Final = 30


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ghép lại offer đã có (mặc định chạy thử).")
    parser.add_argument(
        "--category",
        choices=[c.value for c in REMATCH_CATEGORIES],
        help="chỉ một nhóm (mặc định: mọi nhóm tầng 1)",
    )
    parser.add_argument(
        "--site", choices=[s.value for s in SiteKey], help="chỉ offer của một trang"
    )
    parser.add_argument("--apply", action="store_true", help="ghi thay đổi vào CSDL")
    return parser.parse_args(argv)


def format_report(report: RematchReport) -> list[str]:
    """Báo cáo tiếng Việt cho người chạy lệnh."""
    mode = "Đã ghi" if report.applied else "Chạy thử (chưa ghi; thêm --apply để ghi)"
    lines = [
        f"{mode}: xét {report.offers_checked} offer.",
        f"  Chuyển sản phẩm: {len(report.moves)} offer",
        f"  Sản phẩm mới: {report.products_created}",
        f"  Sửa hãng/tên/mã: {len(report.products_renamed)} sản phẩm",
        f"  Dựng lại thông số khác trước: {len(report.products_specs_changed)} sản phẩm",
        f"  Xóa sản phẩm không còn offer: {len(report.products_deleted)}",
    ]
    if report.orphans_kept:
        ids = ", ".join(f"#{pid}" for pid in report.orphans_kept)
        lines.append(f"  Giữ lại vì còn trong danh sách mua/cảnh báo (không còn offer): {ids}")
    for move in report.moves[:MAX_LISTED_MOVES]:
        target = f"#{move.to_product_id}" if move.to_product_id is not None else "sản phẩm mới"
        lines.append(
            f"    offer #{move.offer_id} {move.title[:70]!r}: #{move.from_product_id} → {target}"
            f" ({move.method.value})"
        )
    if len(report.moves) > MAX_LISTED_MOVES:
        lines.append(f"    … và {len(report.moves) - MAX_LISTED_MOVES} offer khác")
    if not report.changed:
        lines.append("Không có gì thay đổi.")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_console()
    logging.basicConfig(level=logging.WARNING)
    categories = [Category(args.category)] if args.category else list(REMATCH_CATEGORIES)
    site = SiteKey(args.site) if args.site else None

    engine = get_engine(get_settings().database_url.get_secret_value())
    try:
        with Session(engine) as session:
            report = RematchService(session).run(categories, site=site, apply=args.apply)
            if args.apply:
                session.commit()
            else:
                session.rollback()
    finally:
        engine.dispose()
    print("\n".join(format_report(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
