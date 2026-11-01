"""T11.4: `scripts.demo_price_drop` chuẩn bị bước "làm mới giá → cảnh báo" của demo."""

from collections.abc import Callable

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer, PriceAlert, PriceHistory
from app.domain.enums import (
    AlertChannel,
    AlertStatus,
    Category,
    ScrapeTrigger,
    SiteKey,
    StockStatus,
)
from app.services.alert_service import AlertService
from scripts.demo_price_drop import DemoPriceError, prepare_price_drop
from tests.integration.test_pipeline import BASE, NOW, Clock, mock_fetcher, pipeline
from tests.service_support import add_offer, add_product


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def _alerts(session: Session, product_id: int) -> list[PriceAlert]:
    return list(session.exec(select(PriceAlert).where(PriceAlert.product_id == product_id)).all())


def _history(session: Session, offer_id: int) -> list[int]:
    rows = session.exec(
        select(PriceHistory).where(PriceHistory.offer_id == offer_id).order_by(col(PriceHistory.id))
    ).all()
    return [row.price for row in rows]


def test_picks_the_cheapest_active_mock_shop_laptop_and_raises_its_price(
    db_session: Session,
) -> None:
    laptop = add_product(db_session)
    cheap = add_offer(db_session, laptop, price=15_000_000)
    add_offer(db_session, laptop, price=12_000_000, is_active=False)
    add_offer(db_session, laptop, price=11_000_000, stock_status=StockStatus.out_of_stock)
    add_offer(db_session, laptop, site=SiteKey.gearvn, price=10_000_000)
    mouse = add_product(db_session, category=Category.mouse)
    add_offer(db_session, mouse, price=500_000)

    prepared = prepare_price_drop(db_session, bump_percent=20, now=NOW)

    assert prepared.offer_id == cheap.id and not prepared.already_prepared
    assert (prepared.shop_price, prepared.raised_price) == (15_000_000, 18_000_000)
    assert prepared.shop_price is not None
    assert prepared.shop_price < prepared.target_price < prepared.raised_price
    assert cheap.price == 18_000_000
    assert cheap.id is not None and _history(db_session, cheap.id) == [15_000_000, 18_000_000]
    (alert,) = _alerts(db_session, laptop.id or 0)
    assert (alert.target_price, alert.channel, alert.destination, alert.status) == (
        prepared.target_price,
        AlertChannel.email,
        "mock@example.com",
        AlertStatus.active,
    )


def test_running_again_while_the_alert_is_pending_changes_nothing(db_session: Session) -> None:
    laptop = add_product(db_session)
    offer = add_offer(db_session, laptop, price=15_000_000)
    first = prepare_price_drop(db_session, now=NOW)

    second = prepare_price_drop(db_session, now=NOW)

    assert second.already_prepared
    assert (second.alert_id, second.raised_price, second.target_price) == (
        first.alert_id,
        first.raised_price,
        first.target_price,
    )
    assert offer.price == first.raised_price
    assert len(_alerts(db_session, laptop.id or 0)) == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"site": SiteKey.gearvn}, "mock-shop"),
        ({"is_active": False}, "không còn bán"),
        ({"stock_status": StockStatus.out_of_stock}, "hết hàng"),
    ],
)
def test_an_explicit_offer_must_be_an_active_mock_shop_offer(
    db_session: Session, overrides: dict[str, object], message: str
) -> None:
    offer = add_offer(db_session, add_product(db_session), price=15_000_000, **overrides)

    with pytest.raises(DemoPriceError, match=message):
        prepare_price_drop(db_session, offer_id=offer.id, now=NOW)

    assert offer.price == 15_000_000


def test_without_any_mock_shop_laptop_offer_it_explains_what_to_run_first(
    db_session: Session,
) -> None:
    with pytest.raises(DemoPriceError, match="Chạy ngay"):
        prepare_price_drop(db_session, now=NOW)


@pytest.mark.parametrize("bump", [0, 101])
def test_bump_outside_1_to_100_percent_is_rejected(db_session: Session, bump: int) -> None:
    add_offer(db_session, add_product(db_session), price=15_000_000)

    with pytest.raises(DemoPriceError, match="--bump"):
        prepare_price_drop(db_session, bump_percent=bump, now=NOW)


async def test_the_next_mock_shop_run_sees_the_price_drop_and_reports_the_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    url = f"{BASE}/p/asus-mock-strix-15-x01-mk-la001"
    offer = db_session.exec(select(Offer).where(col(Offer.url) == url)).one()
    prepared = prepare_price_drop(db_session, offer_id=offer.id, now=clock.now)
    db_session.flush()

    result = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert offer.id in result.changed_offer_ids
    db_session.refresh(offer)
    assert prepared.shop_price is not None
    assert offer.price == prepared.shop_price < prepared.target_price
    due = AlertService(db_session, now=clock).find_due(list(result.changed_offer_ids))
    assert [alert.alert_id for alert in due] == [prepared.alert_id]


@pytest.mark.parametrize("price", [1, 500, 999, 50_300])
def test_the_threshold_always_sits_strictly_between_the_two_prices(
    db_session: Session, price: int
) -> None:
    add_offer(db_session, add_product(db_session), price=price)

    prepared = prepare_price_drop(db_session, bump_percent=1, now=NOW)

    assert prepared.shop_price is not None
    assert prepared.shop_price < prepared.target_price < prepared.raised_price


async def test_default_choice_on_the_real_mock_shop_skips_the_out_of_stock_laptop(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    """Review: hai laptop rẻ nhất của mock-shop cùng giá, cái lưu trước đang hết hàng."""
    pipe = pipeline(factory, mock_fetcher(), clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    prepared = prepare_price_drop(db_session, now=clock.now)  # không truyền offer_id
    db_session.flush()
    result = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    picked = db_session.get(Offer, prepared.offer_id)
    assert picked is not None and picked.stock_status is not StockStatus.out_of_stock
    due = AlertService(db_session, now=clock).find_due(list(result.changed_offer_ids))
    assert [alert.alert_id for alert in due] == [prepared.alert_id]


async def test_a_second_round_after_a_full_demo_round_works_again(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    """Review: sau một vòng (giá đã về) chạy lại từng báo DuplicateAlert, mã thoát 1."""
    pipe = pipeline(factory, mock_fetcher(), clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    first = prepare_price_drop(db_session, now=clock.now)
    db_session.flush()
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    second = prepare_price_drop(db_session, now=clock.now)
    db_session.flush()
    result = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert not second.already_prepared and second.alert_id != first.alert_id
    assert [a.id for a in _alerts(db_session, second.product_id)] == [second.alert_id]
    due = AlertService(db_session, now=clock).find_due(list(result.changed_offer_ids))
    assert [alert.alert_id for alert in due] == [second.alert_id]
