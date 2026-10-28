"""T9.8: hai "tiến trình" (hai kết nối riêng, đã commit) đặt chỗ cùng một domain."""

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.services.domain_throttle import DbDomainThrottle

DELAY = 2.0


@pytest.fixture
def domain(db_engine: Engine) -> Iterator[str]:
    """Tên miền duy nhất; dọn dòng đã commit sau test (các kết nối ở đây không rollback được)."""
    name = f"shop-{uuid.uuid4().hex[:8]}.example"
    yield name
    with db_engine.begin() as connection:
        connection.execute(text("DELETE FROM domain_throttle WHERE domain = :d"), {"d": name})


async def test_reservations_from_two_processes_are_spaced_by_the_delay(
    db_engine: Engine, domain: str
) -> None:
    first = DbDomainThrottle(lambda: Session(db_engine))
    second = DbDomainThrottle(lambda: Session(db_engine))

    waits = await asyncio.gather(
        *((first if index % 2 == 0 else second).reserve(domain, DELAY) for index in range(12))
    )

    ordered = sorted(waits)
    assert ordered[0] == pytest.approx(0.0, abs=0.5)
    gaps = [later - earlier for earlier, later in zip(ordered, ordered[1:], strict=False)]
    # Mỗi khe cách khe trước đúng `DELAY` (không có hai request nào chung một khe).
    assert all(gap == pytest.approx(DELAY, abs=0.3) for gap in gaps), gaps


async def test_the_slot_is_kept_after_the_caller_returns(db_engine: Engine, domain: str) -> None:
    throttle = DbDomainThrottle(lambda: Session(db_engine))
    await throttle.reserve(domain, DELAY)

    with db_engine.connect() as connection:
        remaining = connection.execute(
            text(
                "SELECT extract(epoch FROM next_allowed_at - clock_timestamp())"
                " FROM domain_throttle WHERE domain = :d"
            ),
            {"d": domain},
        ).scalar_one()

    assert float(remaining) == pytest.approx(DELAY, abs=0.5)


async def test_a_database_error_is_raised_to_the_caller(domain: str) -> None:
    def unreachable() -> Session:
        raise OperationalError("connect", {}, ConnectionError("db down"))

    throttle = DbDomainThrottle(unreachable)

    with pytest.raises(OperationalError):
        await throttle.reserve(domain, DELAY)
