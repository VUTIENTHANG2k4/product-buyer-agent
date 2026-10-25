"""Chuẩn bị bước "làm mới giá → cảnh báo" của kịch bản demo (docs/10 §7, T11.4).

Chạy từ `backend/`: `uv run python -m scripts.demo_price_drop [--offer-id N] [--bump 15]
[--email mock@example.com]` (trong Docker: `make demo-price-drop`).

Mock-shop không có điều khiển giá, nên lệnh giả lập "lần trước shop bán đắt hơn": nâng giá của một
offer mock-shop thêm `--bump` % kèm một dòng `price_history`, rồi tạo cảnh báo với ngưỡng nằm giữa
giá cũ và giá đã nâng. Lượt "Chạy ngay: Mock Shop – Laptop" kế tiếp đọc lại giá thật của mock-shop,
pipeline thấy giá giảm và cảnh báo được đánh giá. Chỉ đụng offer `mockshop` (dữ liệu hư cấu).
Chạy lại khi cảnh báo của lần trước còn chờ thì không đổi gì (chỉ in trạng thái).
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlmodel import Session, col, select

from app.config import get_settings
from app.db.engine import get_engine
from app.db.models import Offer, PriceAlert, Product, utc_now
from app.db.repositories.price_alerts import PriceAlertRepository
from app.db.repositories.price_history import PriceHistoryRepository
from app.domain.catalog import AlertCreate
from app.domain.enums import AlertChannel, AlertStatus, Category, SiteKey
from app.domain.errors import AppError
from app.services.alert_service import AlertService
from scripts.scrape import configure_console

logger = logging.getLogger("demo_price_drop")

DEFAULT_BUMP_PERCENT: Final = 15
DEFAULT_EMAIL: Final = "mock@example.com"


class DemoPriceError(Exception):
    """Không chuẩn bị được (không có offer mock-shop phù hợp, offer không phải mock-shop...)."""


@dataclass(frozen=True)
class PreparedDrop:
    offer_id: int
    product_id: int
    product_name: str
    shop_price: int  # VND, giá mock-shop sẽ trả lại ở lượt thu thập kế tiếp
    raised_price: int  # VND, giá đã nâng đang lưu trong CSDL
    target_price: int  # VND, ngưỡng cảnh báo (shop_price <= target < raised_price)
    alert_id: int
    already_prepared: bool


def _pick_offer(session: Session, offer_id: int | None) -> Offer:
    if offer_id is not None:
        offer = session.get(Offer, offer_id)
        if offer is None:
            raise DemoPriceError(f"Không có offer #{offer_id}.")
        if offer.site is not SiteKey.mockshop:
            raise DemoPriceError(
                f"Offer #{offer_id} thuộc {offer.site.value}; lệnh chỉ đổi giá offer mock-shop."
            )
        if not offer.is_active:
            raise DemoPriceError(f"Offer #{offer_id} không còn bán.")
        return offer
    statement = (
        select(Offer)
        .join(Product, col(Product.id) == col(Offer.product_id))
        .where(
            Offer.site == SiteKey.mockshop,
            col(Offer.is_active).is_(True),
            Product.category == Category.laptop,
        )
        .order_by(col(Offer.price), col(Offer.id))
    )
    offer = session.exec(statement).first()
    if offer is None:
        raise DemoPriceError(
            "Chưa có offer laptop nào của mock-shop: chạy 'Chạy ngay: Mock Shop – Laptop' trước."
        )
    return offer


def _pending_alert(session: Session, product_id: int, email: str, price: int) -> PriceAlert | None:
    """Cảnh báo email còn chờ của lần chạy trước (ngưỡng thấp hơn giá đang lưu)."""
    for alert in PriceAlertRepository(session).list_for_products([product_id]):
        if (
            alert.status is AlertStatus.active
            and alert.channel is AlertChannel.email
            and alert.destination == email.strip().lower()
            and alert.target_price < price
        ):
            return alert
    return None


def prepare_price_drop(
    session: Session,
    *,
    offer_id: int | None = None,
    bump_percent: int = DEFAULT_BUMP_PERCENT,
    email: str = DEFAULT_EMAIL,
    now: datetime | None = None,
) -> PreparedDrop:
    """Nâng giá một offer mock-shop và tạo cảnh báo; chỉ `flush`, người gọi commit."""
    if not 1 <= bump_percent <= 100:
        raise DemoPriceError("--bump phải trong khoảng 1..100 (%).")
    offer = _pick_offer(session, offer_id)
    assert offer.id is not None
    product = session.get(Product, offer.product_id)
    assert product is not None and product.id is not None

    pending = _pending_alert(session, product.id, email, offer.price)
    if pending is not None and pending.id is not None:
        last = PriceHistoryRepository(session).list_for_offer(offer.id)
        shop_price = last[-2].price if len(last) >= 2 else pending.target_price
        return PreparedDrop(
            offer_id=offer.id,
            product_id=product.id,
            product_name=product.canonical_name,
            shop_price=shop_price,
            raised_price=offer.price,
            target_price=pending.target_price,
            alert_id=pending.id,
            already_prepared=True,
        )

    shop_price = offer.price
    raised = shop_price + max(1_000, shop_price * bump_percent // 100 // 1_000 * 1_000)
    target = (shop_price + raised) // 2 // 1_000 * 1_000
    offer.price = raised
    session.add(offer)
    session.flush()
    moment = now or utc_now()
    PriceHistoryRepository(session).record_snapshot(offer, now=moment)
    alert = AlertService(session, now=lambda: moment).create(
        AlertCreate(
            product_id=product.id,
            target_price=target,
            channel=AlertChannel.email,
            destination=email,
        )
    )
    return PreparedDrop(
        offer_id=offer.id,
        product_id=product.id,
        product_name=product.canonical_name,
        shop_price=shop_price,
        raised_price=raised,
        target_price=target,
        alert_id=alert.alert_id,
        already_prepared=False,
    )


def _vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + " ₫"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chuẩn bị bước đổi giá của demo (docs/10 §7).")
    parser.add_argument("--offer-id", type=int, help="offer mock-shop (mặc định: laptop rẻ nhất)")
    parser.add_argument("--bump", type=int, default=DEFAULT_BUMP_PERCENT, help="% nâng giá")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="nơi nhận cảnh báo")
    args = parser.parse_args(argv)
    configure_console()
    logging.basicConfig(level=logging.WARNING)

    engine = get_engine(get_settings().database_url.get_secret_value())
    try:
        with Session(engine) as session:
            prepared = prepare_price_drop(
                session, offer_id=args.offer_id, bump_percent=args.bump, email=args.email
            )
            session.commit()
    except (DemoPriceError, AppError) as error:
        print(f"Không chuẩn bị được: {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    status = "Đã chuẩn bị từ trước" if prepared.already_prepared else "Đã chuẩn bị"
    print(f"{status}: {prepared.product_name} (offer #{prepared.offer_id})")
    print(
        f"  Giá đang lưu: {_vnd(prepared.raised_price)} (mock-shop bán {_vnd(prepared.shop_price)})"
    )
    print(f"  Cảnh báo #{prepared.alert_id}: báo khi ≤ {_vnd(prepared.target_price)}")
    print("Bước tiếp: /admin → 'Chạy ngay: Mock Shop – Laptop' (nhập captcha nếu được hỏi).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
