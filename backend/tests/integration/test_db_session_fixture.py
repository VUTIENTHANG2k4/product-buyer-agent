"""Fixture `db_session` (tests/conftest.py): rollback sau mỗi test, kể cả khi code gọi commit()."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError
from sqlmodel import Session

from tests.factories import make_product


def _insert_and_commit(session: Session) -> None:
    assert session.execute(text("SELECT count(*) FROM product")).scalar_one() == 0
    session.add(make_product())
    session.commit()
    assert session.execute(text("SELECT count(*) FROM product")).scalar_one() == 1


# Hai test giống hệt nhau: nếu rollback hỏng, test chạy sau thấy dòng của test trước và đỏ.
def test_committed_rows_do_not_leak_into_next_test_first(db_session: Session) -> None:
    _insert_and_commit(db_session)


def test_committed_rows_do_not_leak_into_next_test_second(db_session: Session) -> None:
    _insert_and_commit(db_session)


def test_failed_statement_inside_savepoint_keeps_the_transaction_usable(
    db_session: Session,
) -> None:
    db_session.add(make_product())
    db_session.flush()
    with pytest.raises(DataError), db_session.begin_nested():
        db_session.execute(text("SELECT 1/0"))
    assert db_session.execute(text("SELECT count(*) FROM product")).scalar_one() == 1
