"""T7.1: `session_scope` commit khi xong, rollback khi lỗi; dependency `get_session` dùng nó."""

from typing import Any

import pytest

from app.services import database


class FakeSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.events.append("close")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    session = FakeSession()
    monkeypatch.setattr(database, "session_factory", lambda url: lambda: session)
    return session


def test_scope_commits_then_closes_when_the_block_succeeds(fake: FakeSession) -> None:
    with database.session_scope("postgresql+psycopg://x") as session:
        assert id(session) == id(fake)

    assert fake.events == ["commit", "close"]


def test_scope_rolls_back_and_reraises_when_the_block_fails(fake: FakeSession) -> None:
    with (
        pytest.raises(RuntimeError, match="boom"),
        database.session_scope("postgresql+psycopg://x"),
    ):
        raise RuntimeError("boom")

    assert fake.events == ["rollback", "close"]


def test_scope_rolls_back_when_commit_itself_fails(fake: FakeSession) -> None:
    def failing_commit() -> None:
        fake.events.append("commit")
        raise OSError("db gone")

    fake.commit = failing_commit  # type: ignore[method-assign]

    with pytest.raises(OSError, match="db gone"), database.session_scope("postgresql+psycopg://x"):
        pass

    assert fake.events == ["commit", "rollback", "close"]
