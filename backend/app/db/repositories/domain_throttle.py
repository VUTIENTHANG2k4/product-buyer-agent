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

        Khe mới = max(khe gần nhất + `delay_s` của request này, bây giờ): khoảng cách từ khe trước
        là độ trễ của request MỚI (như `DomainRateLimiter` trong tiến trình), nên `Crawl-delay` lớn
        của request sau vẫn được giữ dù request trước chỉ dùng độ trễ nhỏ. Một câu `INSERT ... ON
        CONFLICT DO UPDATE` nên khóa dòng của PostgreSQL xếp hàng các tiến trình; dùng đồng hồ của
        CSDL nên không lệ thuộc giờ từng máy. Chỉ `flush`; nơi gọi commit để giữ chỗ.
        """
        delay = cast(f"{delay_s:.3f} seconds", INTERVAL)
        now = func.clock_timestamp()
        table = DomainThrottle.__table__  # type: ignore[attr-defined]
        upsert = insert(DomainThrottle).values(domain=domain, last_slot_at=now)
        statement = upsert.on_conflict_do_update(
            index_elements=[table.c.domain],
            set_={"last_slot_at": func.greatest(table.c.last_slot_at + delay, now)},
        ).returning(func.extract("epoch", table.c.last_slot_at - now))
        waited = self._session.execute(statement).scalar_one()
        self._session.flush()
        return max(0.0, float(Decimal(waited)))
