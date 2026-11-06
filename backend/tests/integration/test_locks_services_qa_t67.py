"""QA T6.7g: danh sách/cảnh báo rỗng, id ngoài miền, khóa advisory (Unicode, email hoa/thường) và
tranh chấp thật giữa nhiều kết nối (không deadlock, không tạo trùng).

Test đồng thời commit dữ liệu bằng kết nối thật nên tự dọn, rồi kiểm số dòng các bảng không đổi.
"""

import contextlib
import threading
import unicodedata
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func
from sqlmodel import Session, col, select

from app.db.models import Offer, PriceAlert, Product, ShoppingList, ShoppingListItem
from app.db.repositories import PriceAlertRepository, ShoppingListRepository
from app.db.repositories.locks import advisory_xact_lock
from app.domain.catalog import AlertCreate
from app.domain.enums import AlertChannel, AlertStatus
from app.domain.errors import DuplicateAlert, ListNotFound, ValidationFailed
from app.services.alert_service import AlertService
from app.services.shopping_list_service import MAX_NAME_LENGTH, ShoppingListService
from tests.factories import (
    make_offer,
    make_price_alert,
    make_product,
    make_shopping_list,
    make_shopping_list_item,
)
from tests.service_support import make_settings

SETTINGS = make_settings()
INT4_OVER = 2**31


# ---- rỗng / ngoài miền ------------------------------------------------------------------------
def test_list_lists_with_no_lists_returns_an_empty_list(db_session: Session) -> None:
    assert ShoppingListService(db_session).list_lists() == []


def test_list_alerts_with_no_alerts_returns_an_empty_list_for_every_filter(
    db_session: Session,
) -> None:
    service = AlertService(db_session, SETTINGS)

    assert service.list_alerts() == []
    assert [service.list_alerts(status) for status in AlertStatus] == [[]] * len(AlertStatus)


@pytest.mark.parametrize("offer_ids", [[], [0], [-1], [INT4_OVER], [INT4_OVER, 0, -5]])
def test_find_due_with_empty_or_out_of_range_offer_ids_returns_nothing(
    db_session: Session, offer_ids: list[int]
) -> None:
    product = make_product()
    db_session.add(product)
    db_session.flush()
    db_session.add(make_offer(product.id or 0, price=1_000_000))
    db_session.add(make_price_alert(product.id or 0, target_price=5_000_000))
    db_session.flush()

    assert AlertService(db_session, SETTINGS).find_due(offer_ids) == []


def test_find_due_without_any_alert_returns_nothing(db_session: Session) -> None:
    assert AlertService(db_session, SETTINGS).find_due() == []


@pytest.mark.parametrize("list_id", [0, -1, INT4_OVER, 2**63 - 1])
def test_get_list_with_an_id_outside_the_key_range_is_not_found(
    db_session: Session, list_id: int
) -> None:
    with pytest.raises(ListNotFound):
        ShoppingListService(db_session).get_list(list_id)


def test_list_lists_keeps_empty_lists_next_to_filled_ones(db_session: Session) -> None:
    empty = make_shopping_list(name="QA rỗng")
    filled = make_shopping_list(name="QA đầy")
    db_session.add_all([empty, filled])
    db_session.flush()
    product = make_product()
    db_session.add(product)
    db_session.flush()
    db_session.add(make_offer(product.id or 0, price=2_000_000))
    db_session.add(make_shopping_list_item(filled.id or 0, product.id or 0, quantity=3))
    db_session.flush()

    by_name = {s.name: s for s in ShoppingListService(db_session).list_lists()}

    assert (by_name["QA rỗng"].item_count, by_name["QA rỗng"].total_price) == (0, 0)
    assert (by_name["QA đầy"].item_count, by_name["QA đầy"].total_price) == (1, 6_000_000)


def test_product_shared_by_two_lists_is_counted_in_each_list_separately(
    db_session: Session,
) -> None:
    product = make_product()
    db_session.add(product)
    db_session.flush()
    db_session.add(make_offer(product.id or 0, price=1_000_000))
    first, second = make_shopping_list(name="QA một"), make_shopping_list(name="QA hai")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(make_shopping_list_item(first.id or 0, product.id or 0, quantity=1))
    db_session.add(make_shopping_list_item(second.id or 0, product.id or 0, quantity=4))
    db_session.flush()

    by_name = {s.name: s for s in ShoppingListService(db_session).list_lists()}

    assert by_name["QA một"].total_price == 1_000_000
    assert by_name["QA hai"].total_price == 4_000_000
    assert by_name["QA hai"].item_count == by_name["QA một"].item_count == 1


def test_item_whose_product_has_no_buyable_offer_still_counts_but_adds_no_price(
    db_session: Session,
) -> None:
    product = make_product()
    gone = make_product()
    db_session.add_all([product, gone])
    db_session.flush()
    db_session.add(make_offer(product.id or 0, price=1_000_000))
    db_session.add(make_offer(gone.id or 0, price=9_000_000, is_active=False))
    shopping_list = make_shopping_list(name="QA hết offer")
    db_session.add(shopping_list)
    db_session.flush()
    db_session.add(make_shopping_list_item(shopping_list.id or 0, product.id or 0))
    db_session.add(make_shopping_list_item(shopping_list.id or 0, gone.id or 0))
    db_session.flush()

    summary = ShoppingListService(db_session).list_lists()[0]
    detail = ShoppingListService(db_session).get_list(shopping_list.id or 0)

    assert (summary.item_count, summary.total_price) == (2, 1_000_000)
    assert sorted(i.current_price or 0 for i in detail.items) == [0, 1_000_000]


def test_product_in_a_list_cannot_be_deleted_so_items_never_dangle(db_session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    product = make_product()
    db_session.add(product)
    db_session.flush()
    shopping_list = make_shopping_list(name="QA khóa ngoại")
    db_session.add(shopping_list)
    db_session.flush()
    db_session.add(make_shopping_list_item(shopping_list.id or 0, product.id or 0))
    db_session.flush()

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.exec(delete(Product).where(col(Product.id) == product.id))


def test_alert_for_a_product_without_offers_has_no_current_price_and_is_listed(
    db_session: Session,
) -> None:
    product = make_product()
    db_session.add(product)
    db_session.flush()
    db_session.add(make_price_alert(product.id or 0))
    db_session.flush()

    views = AlertService(db_session, SETTINGS).list_alerts()

    assert [v.current_best_price for v in views] == [None]
    assert AlertService(db_session, SETTINGS).find_due() == []


# ---- khóa: khớp khóa nghiệp vụ trong một transaction ------------------------------------------
def test_get_or_create_returns_the_same_list_for_nfc_and_nfd_spellings(db_session: Session) -> None:
    service = ShoppingListService(db_session)
    name = "Máy tầm trung"

    first = service.get_or_create(unicodedata.normalize("NFD", name))
    second = service.get_or_create(unicodedata.normalize("NFC", name))

    assert first.list_id == second.list_id
    assert first.name == unicodedata.normalize("NFC", name)


def test_get_or_create_collapses_inner_whitespace_into_one_list(db_session: Session) -> None:
    service = ShoppingListService(db_session)

    first = service.get_or_create("Gaming   PC")
    second = service.get_or_create("  Gaming PC ")

    assert first.list_id == second.list_id


def test_list_name_at_the_length_limit_is_accepted_and_one_more_is_rejected(
    db_session: Session,
) -> None:
    service = ShoppingListService(db_session)

    assert service.get_or_create("x" * MAX_NAME_LENGTH).name == "x" * MAX_NAME_LENGTH
    with pytest.raises(ValidationFailed):
        service.get_or_create("x" * (MAX_NAME_LENGTH + 1))


def test_lock_name_accepts_very_long_unicode_and_empty_names(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)

    repo.lock_name("")
    repo.lock_name("ặ" * 50_000)
    repo.lock_name("💥" * 10)

    assert db_session.exec(select(func.count()).select_from(ShoppingList)).one() == 0


def test_advisory_lock_is_reentrant_within_one_transaction(db_session: Session) -> None:
    advisory_xact_lock(db_session, 6799, "k")
    advisory_xact_lock(db_session, 6799, "k")  # cùng phiên: không tự chặn mình


@pytest.mark.parametrize("destination", ["QA@Example.com", "qa@EXAMPLE.COM", "  qa@example.com  "])
def test_email_destination_case_and_padding_do_not_make_a_second_alert(
    db_session: Session, destination: str
) -> None:
    product = make_product()
    db_session.add(product)
    db_session.flush()
    service = AlertService(db_session, SETTINGS)
    service.create(
        AlertCreate(
            product_id=product.id or 0,
            target_price=20_000_000,
            channel=AlertChannel.email,
            destination="qa@example.com",
        )
    )

    with pytest.raises(DuplicateAlert):
        service.create(
            AlertCreate(
                product_id=product.id or 0,
                target_price=20_000_000,
                channel=AlertChannel.email,
                destination=destination,
            )
        )


# ---- tranh chấp thật --------------------------------------------------------------------------
@pytest.fixture
def untouched_tables(db_engine: Engine) -> Iterator[None]:
    """Số dòng các bảng test đụng tới phải bằng nhau trước và sau test (đã dọn sạch)."""
    models = (ShoppingList, ShoppingListItem, PriceAlert, Product, Offer)

    def counts() -> list[int]:
        with Session(db_engine) as session:
            return [int(session.exec(select(func.count()).select_from(m)).one()) for m in models]

    before = counts()
    yield
    assert counts() == before


@pytest.fixture
def committed_product(db_engine: Engine, untouched_tables: None) -> Iterator[int]:
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
            session.exec(delete(Product).where(col(Product.id) == product_id))
            session.commit()


def run_jobs(engine: Engine, jobs: list[Callable[[Session], Any]]) -> list[Any]:
    """Mỗi job chạy trong luồng riêng với session riêng; trả kết quả hoặc exception theo thứ tự."""
    outcomes: list[Any] = [None] * len(jobs)
    done = [False] * len(jobs)

    def target(index: int) -> None:
        with Session(engine) as session:
            try:
                value: Any = jobs[index](session)
                session.commit()
            except Exception as error:
                session.rollback()
                value = error
        outcomes[index] = value
        done[index] = True

    threads = [threading.Thread(target=target, args=(i,)) for i in range(len(jobs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(done), "một luồng không kết thúc sau 30 giây (nghi deadlock)"
    return outcomes


def widen(monkeypatch: pytest.MonkeyPatch, owner: type, method: str, parties: int) -> None:
    """Sau bước kiểm tra, mỗi luồng chờ các luồng kia tối đa 1 giây để cửa sổ đua rộng ra."""
    barrier = threading.Barrier(parties, timeout=1)
    original = getattr(owner, method)

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        return result

    monkeypatch.setattr(owner, method, wrapped)


def lists_named(engine: Engine, names: list[str]) -> list[ShoppingList]:
    with Session(engine) as session:
        return list(session.exec(select(ShoppingList).where(col(ShoppingList.name).in_(names))))


def delete_lists(engine: Engine, names: list[str]) -> None:
    with Session(engine) as session:
        session.exec(delete(ShoppingList).where(col(ShoppingList.name).in_(names)))
        session.commit()


def test_three_concurrent_get_or_create_make_exactly_one_list(
    db_engine: Engine, untouched_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "QA T6.7 ba luồng"
    widen(monkeypatch, ShoppingListRepository, "get_by_name", 3)
    try:
        outcomes = run_jobs(
            db_engine, [lambda s: ShoppingListService(s).get_or_create(name) for _ in range(3)]
        )

        rows = lists_named(db_engine, [name])
        assert len(rows) == 1
        assert {o.list_id for o in outcomes} == {rows[0].id}
    finally:
        delete_lists(db_engine, [name])


def test_concurrent_get_or_create_with_nfc_and_nfd_spellings_makes_one_list(
    db_engine: Engine, untouched_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    nfc = "QA T6.7 Máy tầm trung"
    nfd = unicodedata.normalize("NFD", nfc)
    widen(monkeypatch, ShoppingListRepository, "get_by_name", 2)
    try:
        outcomes = run_jobs(
            db_engine,
            [
                lambda s: ShoppingListService(s).get_or_create(nfc),
                lambda s: ShoppingListService(s).get_or_create(nfd),
            ],
        )

        assert len(lists_named(db_engine, [nfc])) == 1
        assert len({o.list_id for o in outcomes}) == 1
    finally:
        delete_lists(db_engine, [nfc])


def test_get_or_create_for_different_names_does_not_wait_for_each_other(
    db_engine: Engine, untouched_tables: None
) -> None:
    names = ["QA T6.7 khác một", "QA T6.7 khác hai"]
    try:
        outcomes = run_jobs(
            db_engine,
            [lambda s, n=n: ShoppingListService(s).get_or_create(n) for n in names],  # type: ignore[misc]
        )

        assert len({o.list_id for o in outcomes}) == 2
    finally:
        delete_lists(db_engine, names)


def alert_request(product_id: int, target: int, destination: str) -> AlertCreate:
    return AlertCreate(
        product_id=product_id,
        target_price=target,
        channel=AlertChannel.email,
        destination=destination,
    )


def live_targets(engine: Engine, product_id: int) -> list[tuple[str, int]]:
    with Session(engine) as session:
        rows = session.exec(select(PriceAlert).where(PriceAlert.product_id == product_id)).all()
        return sorted((a.destination, a.target_price) for a in rows)


def test_concurrent_create_with_email_case_variants_makes_one_alert(
    db_engine: Engine, committed_product: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    widen(monkeypatch, PriceAlertRepository, "list_for_products", 2)

    outcomes = run_jobs(
        db_engine,
        [
            lambda s: AlertService(s, SETTINGS).create(
                alert_request(committed_product, 20_000_000, "Race@Example.com")
            ),
            lambda s: AlertService(s, SETTINGS).create(
                alert_request(committed_product, 20_000_000, "race@example.COM")
            ),
        ],
    )

    assert live_targets(db_engine, committed_product) == [("race@example.com", 20_000_000)]
    assert sorted(type(o).__name__ for o in outcomes) == ["AlertView", "DuplicateAlert"]


def test_concurrent_update_and_create_to_the_same_target_never_make_two_equal_alerts(
    db_engine: Engine, committed_product: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(db_engine) as session:
        base = AlertService(session, SETTINGS).create(
            alert_request(committed_product, 25_000_000, "mix@example.com")
        )
        session.commit()
    widen(monkeypatch, PriceAlertRepository, "list_for_products", 2)

    outcomes = run_jobs(
        db_engine,
        [
            lambda s: AlertService(s, SETTINGS).update(base.alert_id, target_price=18_000_000),
            lambda s: AlertService(s, SETTINGS).create(
                alert_request(committed_product, 18_000_000, "mix@example.com")
            ),
        ],
    )

    errors = [o for o in outcomes if isinstance(o, Exception)]
    assert [type(e) for e in errors] == [DuplicateAlert]  # không deadlock, không lỗi khác
    targets = live_targets(db_engine, committed_product)
    assert len(targets) == len(set(targets))  # không có hai cảnh báo y hệt nhau
    assert ("mix@example.com", 18_000_000) in targets


def test_two_concurrent_updates_to_the_same_target_let_only_one_win(
    db_engine: Engine, committed_product: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(db_engine) as session:
        service = AlertService(session, SETTINGS)
        first = service.create(alert_request(committed_product, 25_000_000, "two@example.com"))
        second = service.create(alert_request(committed_product, 30_000_000, "two@example.com"))
        session.commit()
    widen(monkeypatch, PriceAlertRepository, "list_for_products", 2)

    outcomes = run_jobs(
        db_engine,
        [
            lambda s: AlertService(s, SETTINGS).update(first.alert_id, target_price=18_000_000),
            lambda s: AlertService(s, SETTINGS).update(second.alert_id, target_price=18_000_000),
        ],
    )

    assert sorted(type(o).__name__ for o in outcomes) == ["AlertView", "DuplicateAlert"]
    targets = live_targets(db_engine, committed_product)
    assert targets.count(("two@example.com", 18_000_000)) == 1


def test_concurrent_creates_for_different_destinations_are_all_kept(
    db_engine: Engine, committed_product: int
) -> None:
    destinations = [f"d{i}@example.com" for i in range(4)]

    outcomes = run_jobs(
        db_engine,
        [
            lambda s, d=d: AlertService(s, SETTINGS).create(  # type: ignore[misc]
                alert_request(committed_product, 20_000_000, d)
            )
            for d in destinations
        ],
    )

    assert all(not isinstance(o, Exception) for o in outcomes)
    assert [d for d, _ in live_targets(db_engine, committed_product)] == sorted(destinations)


def test_reactivating_a_paused_alert_races_safely_with_a_new_identical_alert(
    db_engine: Engine, committed_product: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(db_engine) as session:
        base = AlertService(session, SETTINGS).create(
            alert_request(committed_product, 20_000_000, "pause@example.com")
        )
        AlertService(session, SETTINGS).update(base.alert_id, status=AlertStatus.paused)
        session.commit()
    widen(monkeypatch, PriceAlertRepository, "list_for_products", 2)

    outcomes = run_jobs(
        db_engine,
        [
            lambda s: AlertService(s, SETTINGS).update(base.alert_id, status=AlertStatus.active),
            lambda s: AlertService(s, SETTINGS).create(
                alert_request(committed_product, 20_000_000, "pause@example.com")
            ),
        ],
    )

    assert sorted(type(o).__name__ for o in outcomes) == ["AlertView", "DuplicateAlert"]
    with Session(db_engine) as session:
        live = session.exec(
            select(PriceAlert).where(
                col(PriceAlert.product_id) == committed_product,
                col(PriceAlert.status).in_([AlertStatus.active, AlertStatus.triggered]),
            )
        ).all()
    assert len(live) == 1
