"""QA M9: biên của bộ đánh giá cảnh báo trên PostgreSQL thật (khóa dòng, lỗi giữa vòng lặp...)."""

import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.db.models import Offer, PriceAlert, Product
from app.domain.catalog import AlertCreate
from app.domain.enums import AlertChannel, AlertStatus, PriceType, SiteKey, StockStatus
from app.domain.errors import ValidationFailed
from app.services.alert_evaluation import AlertEvaluator, EvaluationReport
from app.services.alert_service import AlertService
from tests.factories import make_offer, make_price_alert, make_product
from tests.integration.test_alert_evaluation import FakeNotifier
from tests.service_support import NOW, add_offer, add_product, clock, make_settings

SETTINGS = make_settings()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def evaluator(
    factory: Callable[[], Session], **notifiers: FakeNotifier | Any
) -> tuple[AlertEvaluator, dict[AlertChannel, Any]]:
    mapping = {AlertChannel(name): notifier for name, notifier in notifiers.items()}
    return AlertEvaluator(factory, mapping, SETTINGS, now=clock), mapping


def add_alert(session: Session, product: Product, **overrides: Any) -> PriceAlert:
    overrides.setdefault("target_price", 28_000_000)
    alert = make_price_alert(product.id or 0, **overrides)
    session.add(alert)
    session.flush()
    return alert


def reread(session: Session, alert: PriceAlert) -> PriceAlert:
    session.expire_all()
    return session.get_one(PriceAlert, alert.id)


# ---- nhiều cảnh báo cùng sản phẩm -------------------------------------------------------------
async def test_alerts_of_one_product_with_different_targets_fire_independently(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)
    high = add_alert(db_session, product, target_price=28_000_000, destination="high@example.com")
    exact = add_alert(db_session, product, target_price=27_000_000, destination="exact@example.com")
    low = add_alert(db_session, product, target_price=26_999_999, destination="low@example.com")
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=2, failed=0)
    assert sorted(destination for destination, _, _ in email.sent) == [
        "exact@example.com",
        "high@example.com",
    ]
    assert reread(db_session, high).status is AlertStatus.triggered
    assert reread(db_session, exact).status is AlertStatus.triggered
    assert reread(db_session, low).status is AlertStatus.active


async def test_same_target_on_two_channels_sends_once_per_channel_and_counts_a_missing_one(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)
    by_mail = add_alert(db_session, product)
    by_chat = add_alert(db_session, product, channel=AlertChannel.telegram, destination="@Chat")
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)  # Telegram chưa cấu hình

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=1, failed=1)
    assert reread(db_session, by_mail).status is AlertStatus.triggered
    assert reread(db_session, by_chat).status is AlertStatus.active


# ---- giá hiệu lực ----------------------------------------------------------------------------
async def test_member_offer_is_compared_by_its_public_list_price_not_the_member_price(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    add_offer(
        db_session,
        product,
        price=25_000_000,
        list_price=30_000_000,
        price_type=PriceType.member,
    )
    alert = add_alert(db_session, product, target_price=28_000_000)
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    report = await ev.evaluate(None)

    assert report == EvaluationReport()
    assert email.sent == [] and reread(db_session, alert).status is AlertStatus.active


async def test_message_links_the_cheapest_effective_offer_and_ties_go_to_the_lower_id(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    first = add_offer(db_session, product, price=27_000_000, url="https://a.example/p/1")
    add_offer(db_session, product, price=27_000_000, url="https://b.example/p/2")
    add_offer(
        db_session,
        product,
        price=20_000_000,
        list_price=29_000_000,
        price_type=PriceType.member,
        url="https://c.example/p/3",
    )
    add_alert(db_session, product)
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    await ev.evaluate(None)

    ((_, _, body),) = email.sent
    assert f"Link: {first.url}" in body and "27.000.000 ₫" in body


async def test_products_without_offers_or_with_only_inactive_offers_never_fire(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    bare = add_product(db_session)
    retired = add_product(db_session)
    add_offer(db_session, retired, price=1_000_000, is_active=False)
    sold_out = add_product(db_session)
    add_offer(db_session, sold_out, price=1_000_000, stock_status=StockStatus.out_of_stock)
    alerts = [add_alert(db_session, p) for p in (bare, retired, sold_out)]
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    report = await ev.evaluate(None)

    assert report == EvaluationReport() and email.sent == []
    assert [reread(db_session, a).status for a in alerts] == [AlertStatus.active] * 3


# ---- lỗi giữa vòng lặp ------------------------------------------------------------------------
def operational_error() -> OperationalError:
    return OperationalError("UPDATE price_alert", {}, Exception("server closed the connection"))


async def test_a_database_error_on_one_alert_does_not_stop_the_alerts_after_it(
    db_session: Session, factory: Callable[[], Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)
    broken = add_alert(db_session, product, destination="a@example.com")
    healthy = add_alert(db_session, product, destination="b@example.com")
    real = AlertService.mark_sent
    calls: list[int] = []

    def flaky(self: AlertService, alert_id: int, price: int) -> bool:
        calls.append(alert_id)
        if len(calls) == 1:
            raise operational_error()
        return real(self, alert_id, price)

    monkeypatch.setattr(AlertService, "mark_sent", flaky)
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=1, failed=1)
    assert [destination for destination, _, _ in email.sent] == ["a@example.com", "b@example.com"]
    assert reread(db_session, broken).status is AlertStatus.active  # lần sau thử lại
    assert reread(db_session, healthy).status is AlertStatus.triggered


async def test_a_failing_commit_counts_as_failed_and_the_next_alert_is_still_processed(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)
    first = add_alert(db_session, product, destination="a@example.com")
    second = add_alert(db_session, product, destination="b@example.com")
    sessions: list[Session] = []

    def broken_commit_factory() -> Session:
        session = factory()
        real_commit = session.commit
        state = {"calls": 0}

        def commit() -> None:
            state["calls"] += 1
            if state["calls"] == 1:
                raise operational_error()
            real_commit()

        session.commit = commit  # type: ignore[method-assign]
        sessions.append(session)
        return session

    email = FakeNotifier()
    ev = AlertEvaluator(broken_commit_factory, {AlertChannel.email: email}, SETTINGS, now=clock)

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=1, failed=1)
    assert reread(db_session, first).status is AlertStatus.active
    assert reread(db_session, second).status is AlertStatus.triggered


class Interrupt(BaseException):
    """Giả lập `KeyboardInterrupt`/`SystemExit` đến từ bộ gửi."""


@pytest.fixture
def committed_alert(db_engine: Engine) -> Iterator[tuple[int, int]]:
    with Session(db_engine) as session:
        product = make_product()
        session.add(product)
        session.flush()
        offer = make_offer(product.id or 0, site=SiteKey.mockshop, price=24_000_000)
        alert = make_price_alert(product.id or 0, target_price=25_000_000)
        session.add_all([offer, alert])
        session.commit()
        ids = (offer.id or 0, alert.id or 0, product.id or 0)
    try:
        yield ids[0], ids[1]
    finally:
        with Session(db_engine) as session:
            session.delete(session.get_one(PriceAlert, ids[1]))
            session.delete(session.get_one(Offer, ids[0]))
            session.commit()
            session.delete(session.get_one(Product, ids[2]))
            session.commit()


def test_a_non_exception_error_from_the_notifier_releases_the_row_lock(
    db_engine: Engine, committed_alert: tuple[int, int]
) -> None:
    offer_id, alert_id = committed_alert

    class Dying:
        def send(self, destination: str, subject: str, body: str) -> None:
            raise Interrupt

    ev = AlertEvaluator(lambda: Session(db_engine), {AlertChannel.email: Dying()}, SETTINGS)

    with pytest.raises(Interrupt):
        ev.evaluate_sync([offer_id])

    results: list[object] = []

    def probe() -> None:
        with Session(db_engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '2s'"))
            row = other.execute(
                text("SELECT status FROM price_alert WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": alert_id},
            ).one()
            results.append(row[0])

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(timeout=10)
    assert results == ["active"], "row lock was still held after the interrupt"


# ---- khối lượng -------------------------------------------------------------------------------
async def test_hundreds_of_alerts_each_get_exactly_one_message(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    products = [add_product(db_session) for _ in range(5)]
    for product in products:
        add_offer(db_session, product, price=27_000_000)
    for n in range(300):
        add_alert(db_session, products[n % 5], destination=f"user{n}@example.com")
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    first = await ev.evaluate(None)
    second = await ev.evaluate(None)

    assert first == EvaluationReport(sent=300, failed=0) and second == EvaluationReport()
    assert len({destination for destination, _, _ in email.sent}) == 300 == len(email.sent)


@pytest.mark.parametrize("count", [1_000, 70_000])
async def test_a_huge_list_of_changed_offer_ids_does_not_break_the_evaluation(
    db_session: Session, factory: Callable[[], Session], count: int
) -> None:
    """Ngoài 65.535 tham số một câu lệnh, PostgreSQL từ chối; lượt thu thập lớn không được làm
    mất toàn bộ bước đánh giá."""
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    add_alert(db_session, product)
    ids: Sequence[int] = [offer.id or 0, *range(10**6, 10**6 + count)]
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    report = await ev.evaluate(ids)

    assert report == EvaluationReport(sent=1, failed=0)


async def test_offer_ids_that_are_negative_zero_duplicated_or_beyond_int4_are_harmless(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    add_alert(db_session, product)
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)

    report = await ev.evaluate([-1, 0, offer.id or 0, offer.id or 0, 2**31, 2**63, -(2**40)])

    assert report == EvaluationReport(sent=1, failed=0) and len(email.sent) == 1


# ---- tạo cảnh báo: nơi nhận -------------------------------------------------------------------
@pytest.mark.parametrize(
    "destination",
    [
        "a@example.com,b@example.com",
        "victim,attacker@example.com",
        "a@example.com;b@example.com",
        "x;y@example.com",
        "Tên <a@example.com>",
    ],
)
def test_an_email_destination_must_be_a_single_plain_address(
    db_session: Session, destination: str
) -> None:
    """BUG-M9-4: dấu phẩy/chấm phẩy/ngoặc lọt qua regex; `message["To"]` của SMTP coi chuỗi là
    danh sách địa chỉ nên thư đi tới người nhận ngoài ý muốn (kể cả "victim" cục bộ)."""
    product = add_product(db_session)
    service = AlertService(db_session, SETTINGS, now=clock)

    with pytest.raises(ValidationFailed):
        service.create(
            AlertCreate(
                product_id=product.id or 0,
                target_price=1_000_000,
                channel=AlertChannel.email,
                destination=destination,
            )
        )


def test_telegram_destinations_with_unusual_characters_are_stored_verbatim(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    service = AlertService(db_session, SETTINGS, now=clock)

    view = service.create(
        AlertCreate(
            product_id=product.id or 0,
            target_price=1_000_000,
            channel=AlertChannel.telegram,
            destination="-1001234567890",
        )
    )

    assert view.destination == "-1001234567890" and view.status is AlertStatus.active


# ---- vòng đời ---------------------------------------------------------------------------------
async def test_retargeting_a_paused_notified_alert_then_resuming_it_notifies_again(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)
    alert = add_alert(db_session, product)
    email = FakeNotifier()
    ev, _ = evaluator(factory, email=email)
    await ev.evaluate(None)
    db_session.expire_all()  # mỗi request API đọc dòng mới; evaluator ghi bằng session khác
    service = AlertService(db_session, SETTINGS, now=clock)

    service.update(alert.id or 0, status=AlertStatus.paused)
    service.update(alert.id or 0, target_price=27_500_000)  # ngưỡng mới = cảnh báo mới
    paused_report = await ev.evaluate(None)
    service.update(alert.id or 0, status=AlertStatus.active)
    resumed_report = await ev.evaluate(None)

    assert paused_report == EvaluationReport()
    assert resumed_report == EvaluationReport(sent=1, failed=0)
    assert len(email.sent) == 2
    assert reread(db_session, alert).last_notified_at == NOW


# ---- sửa cảnh báo đúng lúc đang gửi -----------------------------------------------------------
def _wait_until_a_session_waits_for_a_lock(engine: Engine, timeout: float = 10) -> bool:
    gate = threading.Event()
    for _ in range(int(timeout / 0.05)):
        with engine.connect() as connection:
            waiting = connection.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            ).scalar_one()
        if waiting:
            return True
        gate.wait(0.05)
    return False


def test_retargeting_an_alert_while_it_is_being_sent_still_makes_it_a_new_alert(
    db_engine: Engine, committed_alert: tuple[int, int]
) -> None:
    """BUG-M9-7: `update` đọc dòng không khóa; UPDATE chỉ ghi cột đã đổi nên khi chờ worker commit
    xong, ngưỡng mới được ghi nhưng `triggered` + `last_notified_price` của ngưỡng cũ vẫn còn
    (đúng lỗi mà `set_target_price` sinh ra để tránh)."""
    offer_id, alert_id = committed_alert
    sending, release = threading.Event(), threading.Event()

    class SlowNotifier:
        def send(self, destination: str, subject: str, body: str) -> None:
            sending.set()
            assert release.wait(timeout=20)

    ev = AlertEvaluator(lambda: Session(db_engine), {AlertChannel.email: SlowNotifier()}, SETTINGS)
    errors: list[BaseException] = []

    def run(action: Callable[[], object]) -> threading.Thread:
        def target() -> None:
            try:
                action()
            except BaseException as error:  # noqa: BLE001 - chuyển về luồng chính
                errors.append(error)

        thread = threading.Thread(target=target)
        thread.start()
        return thread

    def edit() -> None:
        with Session(db_engine) as session:
            AlertService(session, SETTINGS).update(alert_id, target_price=26_000_000)
            session.commit()

    sender = run(lambda: ev.evaluate_sync([offer_id]))
    editor: threading.Thread | None = None
    try:
        assert sending.wait(timeout=15)
        editor = run(edit)
        assert _wait_until_a_session_waits_for_a_lock(db_engine)
    finally:
        release.set()
        sender.join(timeout=20)
        if editor is not None:
            editor.join(timeout=20)

    assert errors == []
    with Session(db_engine) as session:
        saved = session.get_one(PriceAlert, alert_id)
        assert (saved.target_price, saved.status, saved.last_notified_price) == (
            26_000_000,
            AlertStatus.active,
            None,
        )
