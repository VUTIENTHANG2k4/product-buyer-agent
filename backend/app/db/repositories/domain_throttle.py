"""Khe thời gian gửi request theo domain dùng chung giữa các tiến trình (T9.8)."""

from decimal import Decimal

from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import INTERVAL, insert
from sqlmodel import Session

from app.db.models import DomainThrottle


class DomainThrottleRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def reserve(self, domain: str, delay_s: float) -> float:
        """Đặt chỗ cho một request tới `domain`, trả số giây (>= 0) phải chờ trước khi gửi.

        Một câu `INSERT ... ON CONFLICT DO UPDATE` nên khóa dòng của PostgreSQL xếp hàng các tiến
        trình: khe của mỗi request cách khe trước ít nhất `delay_s` giây. Dùng đồng hồ của CSDL nên
        không lệ thuộc giờ từng máy. Chỉ `flush`; nơi gọi commit để giữ chỗ.
        """
        delay = cast(f"{delay_s:.3f} seconds", INTERVAL)
        now = func.clock_timestamp()
        table = DomainThrottle.__table__  # type: ignore[attr-defined]
        upsert = insert(DomainThrottle).values(domain=domain, next_allowed_at=now + delay)
        statement = upsert.on_conflict_do_update(
            index_elements=[table.c.domain],
            set_={"next_allowed_at": func.greatest(table.c.next_allowed_at, now) + delay},
        ).returning(func.extract("epoch", (table.c.next_allowed_at - delay) - now))
        waited = self._session.execute(statement).scalar_one()
        self._session.flush()
        return max(0.0, float(Decimal(waited)))
