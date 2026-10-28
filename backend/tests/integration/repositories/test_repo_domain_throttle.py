"""T9.8: khe thời gian gửi request theo domain, dùng đồng hồ của PostgreSQL."""

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.db.models import DomainThrottle
from app.db.repositories import DomainThrottleRepository


def test_first_reservation_for_a_domain_does_not_wait(db_session: Session) -> None:
    wait = DomainThrottleRepository(db_session).reserve("shop.example", 5.0)

    assert wait == pytest.approx(0.0, abs=0.5)
    row = db_session.get_one(DomainThrottle, "shop.example")
    assert row.next_allowed_at is not None


def test_consecutive_reservations_are_spaced_by_the_delay(db_session: Session) -> None:
    repo = DomainThrottleRepository(db_session)

    waits = [repo.reserve("shop.example", 5.0) for _ in range(4)]

    # Khe thứ k cách khe thứ k-1 đúng 5 giây: thời gian chờ tăng dần ~0, ~5, ~10, ~15 giây.
    assert waits[0] == pytest.approx(0.0, abs=0.5)
    for index, wait in enumerate(waits):
        assert wait == pytest.approx(5.0 * index, abs=1.0)
    assert all(later > earlier for earlier, later in zip(waits, waits[1:], strict=False))


def test_other_domains_do_not_wait_for_each_other(db_session: Session) -> None:
    repo = DomainThrottleRepository(db_session)
    repo.reserve("a.example", 30.0)
    repo.reserve("a.example", 30.0)

    assert repo.reserve("b.example", 30.0) == pytest.approx(0.0, abs=0.5)


def test_an_expired_slot_is_replaced_not_accumulated(db_session: Session) -> None:
    repo = DomainThrottleRepository(db_session)
    repo.reserve("shop.example", 5.0)
    db_session.execute(
        text("UPDATE domain_throttle SET next_allowed_at = now() - interval '1 hour'")
    )

    assert repo.reserve("shop.example", 5.0) == pytest.approx(0.0, abs=0.5)
    # Khe kế tiếp chỉ cách 5 giây, không bị cộng dồn từ mốc cũ đã hết hạn.
    assert repo.reserve("shop.example", 5.0) == pytest.approx(5.0, abs=1.0)


@pytest.mark.parametrize("delay", [0.0, 0.25, 6.123])
def test_fractional_and_zero_delays_are_accepted(db_session: Session, delay: float) -> None:
    repo = DomainThrottleRepository(db_session)
    repo.reserve("frac.example", delay)

    assert repo.reserve("frac.example", delay) == pytest.approx(delay, abs=0.5)
