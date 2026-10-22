"""Phiên CSDL cho lớp API: `app/api` không import `app/db`, nên engine và session đi qua đây.

Repository chỉ `flush`; nơi gọi giữ transaction. `session_scope` là một transaction cho một request:
commit khi xong, rollback khi có lỗi.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlmodel import Session

from app.db.engine import get_engine

SessionFactory = Callable[[], Session]


def session_factory(database_url: str) -> SessionFactory:
    """Hàm tạo session mới cho `database_url` (engine dùng chung theo URL)."""
    engine = get_engine(database_url)
    return lambda: Session(engine)


@contextmanager
def session_scope(database_url: str) -> Iterator[Session]:
    """Một session, commit khi khối `with` kết thúc bình thường và rollback khi có ngoại lệ."""
    with session_factory(database_url)() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
