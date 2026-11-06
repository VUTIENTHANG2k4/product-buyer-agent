"""T6.7g: số truy vấn không tăng theo số danh sách/cảnh báo; tạo trùng đồng thời bị chặn."""

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, delete, event
from sqlmodel import Session, col, select

from app.db.models import PriceAlert, Product, ShoppingList, ShoppingListItem
from app.db.repositories import PriceAlertRepository, ShoppingListRepository
from app.domain.catalog import AlertCreate
from app.domain.enums import AlertChannel
from app.domain.errors import DuplicateAlert
from app.services.alert_service import AlertService
from app.services.shopping_list_service import ShoppingListService
from tests.factories import (
    make_offer,
    make_price_alert,
    make_product,
    make_shopping_list,
    make_shopping_list_item,
)
from tests.service_support import make_settings

SETTINGS = make_settings()


class QueryCounter:
    """Đếm câu lệnh SQL chạy qua một connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self.count = 0

    def _on_execute(self, *_: object) -> None:
        self.count += 1

    def __enter__(self) -> "QueryCounter":
        event.listen(self._connection, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *_: object) -> None:
        event.remove(self._connection, "before_cursor_execute", self._on_execute)


def connection_of(session: Session) -> Connection:
    bind = session.get_bind()
    assert isinstance(bind, Connection)
    return bind


def seed_lists(session: Session, lists: int, items_per_list: int) -> None:
    for _ in range(lists):
        shopping_list = make_shopping_list()
        session.add(shopping_list)
        session.flush()
        for _ in range(items_per_list):
            product = make_product()
            session.add(product)
            session.flush()
            session.add(make_offer(product.id or 0))
            session.add(make_shopping_list_item(shopping_list.id or 0, product.id or 0))
    session.flush()


def count_list_queries(session: Session) -> int:
    session.expire_all()
    with QueryCounter(connection_of(session)) as counter:
        summaries = ShoppingListService(session).list_lists()
    assert sum(s.item_count for s in summaries) > 0
    return counter.count


def test_list_lists_runs_the_same_number_of_queries_for_any_number_of_lists(
    db_session: Session,
) -> None:
    seed_lists(db_session, lists=1, items_per_list=1)
    small = count_list_queries(db_session)

    seed_lists(db_session, lists=5, items_per_list=3)
    large = count_list_queries(db_session)

    assert large == small


def test_list_lists_keeps_each_list_with_its_own_items_and_totals(db_session: Session) -> None:
    seed_lists(db_session, lists=3, items_per_list=2)

    summaries = ShoppingListService(db_session).list_lists()

    assert [s.item_count for s in summaries] == [2, 2, 2]
    assert all(s.total_price == 2 * 27_490_000 for s in summaries)


def test_get_list_queries_do_not_grow_with_the_number_of_items(db_session: Session) -> None:
    def detail_queries(items: int) -> int:
        shopping_list = make_shopping_list()
        db_session.add(shopping_list)
        db_session.flush()
        for _ in range(items):
            product = make_product()
            db_session.add(product)
            db_session.flush()
            db_session.add(make_offer(product.id or 0))
            db_session.add(make_shopping_list_item(shopping_list.id or 0, product.id or 0))
        db_session.flush()
        db_session.expire_all()
        with QueryCounter(connection_of(db_session)) as counter:
            ShoppingListService(db_session).get_list(shopping_list.id or 0)
        return counter.count

    assert detail_queries(8) == detail_queries(1)


def test_list_alerts_runs_the_same_number_of_queries_for_any_number_of_alerts(
    db_session: Session,
) -> None:
    def alert_queries(alerts: int) -> int:
        for _ in range(alerts):
            product = make_product()
            db_session.add(product)
            db_session.flush()
            db_session.add(make_offer(product.id or 0))
            db_session.add(make_price_alert(product.id or 0))
        db_session.flush()
        db_session.expire_all()
        with QueryCounter(connection_of(db_session)) as counter:
            views = AlertService(db_session, SETTINGS).list_alerts()
        assert len(views) >= alerts
        return counter.count

    assert alert_queries(10) == alert_queries(1)


# ---- hai kết nối thật tạo cùng một thứ đồng thời ---------------------------------------------
def widen_race_window(monkeypatch: pytest.MonkeyPatch, owner: type, method: str) -> None:
    """Sau bước "kiểm tra", mỗi luồng chờ luồng kia tối đa 1 giây: không có khóa thì cả hai cùng
    thấy "chưa có" (đua xảy ra chắc chắn); có khóa thì luồng sau bị chặn trước bước kiểm tra nên
    luồng trước hết hạn chờ rồi tạo."""
    barrier = threading.Barrier(2, timeout=1)
    original = getattr(owner, method)

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        return result

    monkeypatch.setattr(owner, method, wrapped)


def run_in_threads(engine: Engine, job: Callable[[Session], Any]) -> list[Any]:
    outcomes: list[Any] = []
    lock = threading.Lock()

    def target() -> None:
        with Session(engine) as session:
            try:
                value: Any = job(session)
                session.commit()
            except Exception as error:
                session.rollback()
                value = error
        with lock:
            outcomes.append(value)

    threads = [threading.Thread(target=target) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(outcomes) == 2
    return outcomes


def test_two_concurrent_get_or_create_make_exactly_one_list(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "T6.7g danh sách đua"
    widen_race_window(monkeypatch, ShoppingListRepository, "get_by_name")
    try:
        outcomes = run_in_threads(
            db_engine, lambda session: ShoppingListService(session).get_or_create(name)
        )

        with Session(db_engine) as session:
            rows = session.exec(select(ShoppingList).where(ShoppingList.name == name)).all()
        assert len(rows) == 1
        assert {o.list_id for o in outcomes} == {rows[0].id}
    finally:
        with Session(db_engine) as session:
            session.exec(delete(ShoppingList).where(col(ShoppingList.name) == name))
            session.commit()


@pytest.fixture
def committed_product(db_engine: Engine) -> Iterator[int]:
    with Session(db_engine) as session:
        product = make_product()
        session.add(product)
        session.commit()
        product_id = product.id or 0
    try:
        yield product_id
    finally:
        with Session(db_engine) as session:
            session.exec(delete(PriceAlert).where(col(PriceAlert.product_id) == product_id))
            session.exec(
                delete(ShoppingListItem).where(col(ShoppingListItem.product_id) == product_id)
            )
            session.exec(delete(Product).where(col(Product.id) == product_id))
            session.commit()


def test_two_concurrent_identical_alerts_make_one_and_the_other_is_a_duplicate(
    db_engine: Engine, committed_product: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    widen_race_window(monkeypatch, PriceAlertRepository, "list_for_products")
    request = AlertCreate(
        product_id=committed_product,
        target_price=20_000_000,
        channel=AlertChannel.email,
        destination="race@example.com",
    )

    outcomes = run_in_threads(
        db_engine, lambda session: AlertService(session, SETTINGS).create(request)
    )

    with Session(db_engine) as session:
        rows = session.exec(
            select(PriceAlert).where(PriceAlert.product_id == committed_product)
        ).all()
    assert len(rows) == 1
    assert sorted(type(o).__name__ for o in outcomes) == ["AlertView", "DuplicateAlert"]
    assert any(isinstance(o, DuplicateAlert) for o in outcomes)


def test_alerts_for_different_destinations_do_not_block_each_other(
    db_engine: Engine, committed_product: int
) -> None:
    def create(destination: str) -> None:
        with Session(db_engine) as session:
            AlertService(session, SETTINGS).create(
                AlertCreate(
                    product_id=committed_product,
                    target_price=20_000_000,
                    channel=AlertChannel.email,
                    destination=destination,
                )
            )
            session.commit()

    create("a@example.com")
    create("b@example.com")

    with Session(db_engine) as session:
        count = len(
            session.exec(select(PriceAlert).where(PriceAlert.product_id == committed_product)).all()
        )
    assert count == 2
