"""T7.6: `events_since` cắt ở SQL và `require_run` không tải sự kiện."""

import uuid
from typing import Any

import pytest
from sqlalchemy import event
from sqlmodel import Session

from app.domain.enums import AgentRunStatus
from app.domain.errors import RunNotFound
from app.services.conversation_service import ConversationService, require_run
from tests.factories import make_agent_run, make_conversation
from tests.service_support import clock


def make_run(session: Session, events: list[Any], **overrides: Any):  # type: ignore[no-untyped-def]
    conversation = make_conversation()
    session.add(conversation)
    session.flush()
    assert conversation.id is not None
    run = make_agent_run(conversation.id, events=events, **overrides)
    session.add(run)
    session.flush()
    return run


def numbered(count: int) -> list[dict[str, Any]]:
    return [{"event": "tool_start", "data": {"n": n}} for n in range(count)]


@pytest.mark.parametrize(
    ("after", "expected"),
    [(0, 6), (1, 5), (5, 1), (6, 0), (7, 0), (10_000, 0), (-1, 6), (-10_000, 6)],
)
def test_events_since_returns_exactly_the_tail(
    db_session: Session, after: int, expected: int
) -> None:
    run = make_run(db_session, numbered(6))

    batch = ConversationService(db_session, now=clock).events_since(run.id, after)

    assert [e["data"]["n"] for e in batch.events] == list(range(6))[max(0, after) :]
    assert len(batch.events) == expected


def test_events_since_on_a_run_without_events_is_empty(db_session: Session) -> None:
    run = make_run(db_session, [])

    batch = ConversationService(db_session, now=clock).events_since(run.id, 0)

    assert batch.events == [] and batch.status is AgentRunStatus.running


def test_events_since_unknown_run_raises(db_session: Session) -> None:
    with pytest.raises(RunNotFound):
        ConversationService(db_session, now=clock).events_since(uuid.uuid4(), 0)


def test_events_since_does_not_select_the_whole_events_column(db_session: Session) -> None:
    run = make_run(db_session, numbered(50))
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        ConversationService(db_session, now=clock).events_since(run.id, 49)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    (query,) = [s for s in statements if "agent_run" in s]
    assert "jsonb_path_query_array" in query
    assert "agent_run.events" in query and "SELECT agent_run.events" not in query


def test_require_run_checks_existence_without_loading_events(db_session: Session) -> None:
    run = make_run(db_session, numbered(3))
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        require_run(lambda: Session(bind=engine, join_transaction_mode="create_savepoint"), run.id)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements and all("events" not in s for s in statements)
    with pytest.raises(RunNotFound):
        require_run(
            lambda: Session(bind=engine, join_transaction_mode="create_savepoint"), uuid.uuid4()
        )
