"""Chuẩn bị bước "làm mới giá → cảnh báo" của kịch bản demo (docs/10 §7, T11.4).

Chạy từ `backend/`: `uv run python -m scripts.demo_price_drop [--offer-id N] [--bump 15]
[--email mock@example.com]` (trong Docker: `make demo-price-drop [ARGS="--bump 20"]`).

Mock-shop không có điều khiển giá, nên lệnh giả lập "lần trước shop bán đắt hơn": nâng giá của một
offer mock-shop còn hàng thêm `--bump` % kèm một dòng `price_history`, rồi tạo cảnh báo với ngưỡng
nằm giữa giá cũ và giá đã nâng. Lượt "Chạy ngay: Mock Shop – Laptop" kế tiếp đọc lại giá thật của
mock-shop, pipeline thấy giá giảm và cảnh báo đến hạn. Chỉ đụng offer `mockshop` (dữ liệu hư cấu).

Chạy lại khi cảnh báo của lần trước còn chờ (giá vẫn đang nâng) thì không đổi gì. Sau một vòng demo
(giá đã về), lần chạy mới thay cảnh báo cũ của cùng nơi nhận cho sản phẩm đó bằng cảnh báo mới, nên
diễn tập rồi trình diễn trên cùng CSDL vẫn lặp lại được.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlmodel import Session, col, select
from sqlmodel.sql.expression import SelectOfScalar

from app.config import get_settings
from app.db.engine import get_engine
from app.db.models import Offer, PriceAlert, Product
from app.db.repositories.price_alerts import PriceAlertRepository, normalize_destination
from app.db.repositories.price_history import PriceHistoryRepository
from app.domain.catalog import AlertCreate
from app.domain.clock import utc_now
from app.domain.enums import AlertChannel, AlertStatus, Category, SiteKey, StockStatus
from app.domain.errors import AppError
from app.services.alert_service import AlertService
from app.services.notifier.message import format_vnd
from scripts.scrape import configure_console

DEFAULT_BUMP_PERCENT: Final = 15
DEFAULT_EMAIL: Final = "mock@example.com"
MIN_BUMP_VND: Final = 1_000  # nâng ít nhất 1.000 ₫ để ngưỡng nằm hẳn giữa hai mức giá


class DemoPriceError(Exception):
    """Không chuẩn bị được (không có offer mock-shop phù hợp, offer không phải mock-shop...)."""


@dataclass(frozen=True)
class PreparedDrop:
    offer_id: int
    product_id: int
    product_name: str
    shop_price: int | None  # VND, giá mock-shop trả lại ở lượt kế tiếp (None: không suy ra được)
    raised_price: int  # VND, giá đã nâng đang lưu trong CSDL
    target_price: int  # VND, ngưỡng cảnh báo (shop_price < target < raised_price)
    alert_id: int
    already_prepared: bool


def _mock_shop_offers() -> SelectOfScalar[Offer]:
    """Offer laptop mock-shop đang bán và còn hàng, rẻ nhất trước (hòa giá: id nhỏ nhất)."""
    return (
        select(Offer)
        .join(Product, col(Product.id) == col(Offer.product_id))
        .where(
            Offer.site == SiteKey.mockshop,
            col(Offer.is_active).is_(True),
            Offer.stock_status != StockStatus.out_of_stock,
            Product.category == Category.laptop,
        )
        .order_by(col(Offer.price), col(Offer.id))
    )


def _pick_offer(session: Session, offer_id: int | None) -> Offer:
    """Offer mock-shop đang bán và còn hàng: offer hết hàng không tính vào giá tốt nhất nên cảnh báo
    của nó không bao giờ đến hạn (`views.sellable`)."""
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
        if offer.stock_status is StockStatus.out_of_stock:
            raise DemoPriceError(f"Offer #{offer_id} đang hết hàng nên cảnh báo sẽ không báo.")
        return offer
    statement = _mock_shop_offers()
    offer = session.exec(statement).first()
    if offer is None:
        raise DemoPriceError(
            "Chưa có offer laptop còn hàng nào của mock-shop: chạy "
            "'Chạy ngay: Mock Shop – Laptop' trước."
        )
    return offer


def _demo_alerts(session: Session, product_id: int, destination: str | None) -> list[PriceAlert]:
    """Cảnh báo email còn hiệu lực (`active`/`triggered`) của sản phẩm, lọc theo `destination`."""
    return [
        alert
        for alert in PriceAlertRepository(session).list_for_products([product_id])
        if alert.channel is AlertChannel.email
        and (destination is None or alert.destination == destination)
    ]


@dataclass(frozen=True)
class _Raised:
    """Offer đang ở trạng thái "đã nâng giá, chờ lượt thu thập": lần lịch sử cuối đắt hơn lần
    trước, và một cảnh báo `active` có ngưỡng nằm giữa hai mức giá."""

    shop_price: int
    alerts: list[PriceAlert]


def _raised_state(session: Session, offer: Offer) -> _Raised | None:
    assert offer.id is not None
    history = PriceHistoryRepository(session).list_for_offer(offer.id)
    if len(history) < 2 or history[-1].price != offer.price or history[-2].price >= offer.price:
        return None
    shop_price = history[-2].price
    alerts = [
        alert
        for alert in _demo_alerts(session, offer.product_id, None)
        if alert.status is AlertStatus.active and shop_price < alert.target_price < offer.price
    ]
    return _Raised(shop_price, alerts) if alerts else None


def _find_raised_offer(session: Session) -> Offer | None:
    """Offer mock-shop còn hàng đang ở trạng thái đã nâng (để chạy lại không nâng offer khác)."""
    for offer in session.exec(_mock_shop_offers()).all():
        if _raised_state(session, offer) is not None:
            return offer
    return None


def _raise_and_target(shop_price: int, bump_percent: int) -> tuple[int, int]:
    """(giá nâng, ngưỡng) với `shop_price < ngưỡng < giá nâng`; giá nâng làm tròn xuống nghìn."""
    raised = shop_price + max(MIN_BUMP_VND, shop_price * bump_percent // 100 // 1_000 * 1_000)
    target = shop_price + (raised - shop_price) // 2
    assert shop_price < target < raised
    return raised, target


def prepare_price_drop(
    session: Session,
    *,
    offer_id: int | None = None,
    bump_percent: int = DEFAULT_BUMP_PERCENT,
    email: str = DEFAULT_EMAIL,
    now: datetime | None = None,
) -> PreparedDrop:
    """Nâng giá một offer mock-shop và tạo cảnh báo; chỉ `flush`, người gọi commit.

    Offer đã được nâng ở lần chạy trước (còn chờ lượt thu thập) được dùng lại: không nâng thêm,
    không đổi sang offer rẻ nhất khác; email mới chỉ được thêm cảnh báo với cùng ngưỡng.
    """
    if not 1 <= bump_percent <= 100:
        raise DemoPriceError("--bump phải trong khoảng 1..100 (%).")
    offer = _find_raised_offer(session) if offer_id is None else None
    offer = offer or _pick_offer(session, offer_id)
    assert offer.id is not None
    product = session.get(Product, offer.product_id)
    assert product is not None and product.id is not None
    destination = normalize_destination(AlertChannel.email, email)
    moment = now or utc_now()
    service = AlertService(session, now=lambda: moment)

    raised_state = _raised_state(session, offer)
    if raised_state is not None:
        mine = next((a for a in raised_state.alerts if a.destination == destination), None)
        if mine is not None and mine.id is not None:
            return _prepared(
                offer, product, raised_state.shop_price, mine.target_price, mine.id, True
            )
        target = raised_state.alerts[0].target_price
        created = service.create(
            AlertCreate(
                product_id=product.id,
                target_price=target,
                channel=AlertChannel.email,
                destination=destination,
            )
        )
        return _prepared(offer, product, raised_state.shop_price, target, created.alert_id, False)

    for old in _demo_alerts(session, product.id, destination):  # cảnh báo của vòng demo trước
        assert old.id is not None
        service.delete(old.id)
    shop_price = offer.price
    history = PriceHistoryRepository(session)
    history.record_snapshot(offer, now=moment)  # mốc giá gốc, để nhận ra trạng thái "đã nâng"
    raised, target = _raise_and_target(shop_price, bump_percent)
    offer.price = raised
    session.add(offer)
    session.flush()
    history.record_snapshot(offer, now=moment)
    created = service.create(
        AlertCreate(
            product_id=product.id,
            target_price=target,
            channel=AlertChannel.email,
            destination=destination,
        )
    )
    return _prepared(offer, product, shop_price, target, created.alert_id, False)


def _prepared(
    offer: Offer,
    product: Product,
    shop_price: int,
    target: int,
    alert_id: int,
    already_prepared: bool,
) -> PreparedDrop:
    assert offer.id is not None and product.id is not None
    return PreparedDrop(
        offer_id=offer.id,
        product_id=product.id,
        product_name=product.canonical_name,
        shop_price=shop_price,
        raised_price=offer.price,
        target_price=target,
        alert_id=alert_id,
        already_prepared=already_prepared,
    )


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
    shop = format_vnd(prepared.shop_price) if prepared.shop_price is not None else "không rõ"
    print(f"{status}: {prepared.product_name} (offer #{prepared.offer_id})")
    print(f"  Giá đang lưu: {format_vnd(prepared.raised_price)} (mock-shop bán {shop})")
    print(f"  Cảnh báo #{prepared.alert_id}: báo khi ≤ {format_vnd(prepared.target_price)}")
    print("Bước tiếp: /admin → 'Chạy ngay: Mock Shop – Laptop' (nhập captcha nếu được hỏi).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
