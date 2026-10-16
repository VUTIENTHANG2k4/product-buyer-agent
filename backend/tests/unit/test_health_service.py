import pytest
from sqlalchemy.exc import OperationalError

from app.services import health_service


class _FakeConnection:
    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.statements: list[str] = []

    def __enter__(self) -> "_FakeConnection":
        if self.fail:
            raise OperationalError("connect", {}, Exception("connection refused"))
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnection:
        return self.connection


def test_check_db_returns_ok_after_select_1(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConnection(fail=False)
    monkeypatch.setattr(health_service, "get_engine", lambda url: _FakeEngine(conn))
    assert health_service.check_db("postgresql+psycopg://x/x") == "ok"
    assert conn.statements == ["SELECT 1"]


def test_check_db_returns_error_when_connection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        health_service, "get_engine", lambda url: _FakeEngine(_FakeConnection(fail=True))
    )
    assert health_service.check_db("postgresql+psycopg://x/x") == "error"
