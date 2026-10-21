"""T7.2: đọc lượt chạy/hội thoại và dọn lượt kẹt của `ConversationService`."""

from datetime import timedelta

import pytest
from sqlmodel import Session

from app.domain.enums import AgentRunStatus, MessageRole
from app.domain.errors import NotFound, RunNotFound
from app.services.conversation_service import (
    STALE_RUN_AFTER,
    ConversationService,
    read_run_events,
    require_run,
)
from tests.factories import make_agent_run, make_conversation, make_message
from tests.service_support import NOW, clock


def service(session: Session) -> ConversationService:
    return ConversationService(session, now=clock)


def run_with_events(session: Session, count: int, **overrides: object):  # type: ignore[no-untyped-def]
    conversation = make_conversation()
    session.add(conversation)
    session.flush()
    assert conversation.id is not None
    events = [{"event": "tool_start", "data": {"n": n}} for n in range(count)]
    run = make_agent_run(conversation.id, events=events, **overrides)
    session.add(run)
    session.flush()
    return run


def test_events_since_returns_the_tail_and_the_status_together(db_session: Session) -> None:
    run = run_with_events(db_session, 3, status=AgentRunStatus.running)

    batch = service(db_session).events_since(run.id, 1)

    assert batch.status is AgentRunStatus.running
    assert [e["data"]["n"] for e in batch.events] == [1, 2]
    assert service(db_session).events_since(run.id, 3).events == []
    assert len(service(db_session).events_since(run.id, -4).events) == 3


def test_get_run_returns_a_snapshot_and_unknown_runs_raise(db_session: Session) -> None:
    run = run_with_events(db_session, 2, intent={"category": "laptop"})

    snapshot = service(db_session).get_run(run.id)

    assert snapshot.run_id == run.id and snapshot.conversation_id == run.conversation_id
    assert snapshot.intent == {"category": "laptop"} and len(snapshot.events) == 2
    import uuid

    with pytest.raises(RunNotFound):
        service(db_session).get_run(uuid.uuid4())


def test_read_helpers_use_a_fresh_short_lived_session(db_session: Session) -> None:
    run = run_with_events(db_session, 2)

    def factory() -> Session:
        return Session(bind=db_session.get_bind(), join_transaction_mode="create_savepoint")

    assert len(read_run_events(factory, run.id, 0).events) == 2
    assert require_run(factory, run.id).run_id == run.id


def test_fail_stale_runs_only_touches_old_running_runs(db_session: Session) -> None:
    old = run_with_events(db_session, 0, created_at=NOW - STALE_RUN_AFTER - timedelta(seconds=1))
    edge = run_with_events(db_session, 0, created_at=NOW - STALE_RUN_AFTER)
    fresh = run_with_events(db_session, 0, created_at=NOW - timedelta(minutes=1))
    done = run_with_events(
        db_session,
        0,
        status=AgentRunStatus.succeeded,
        created_at=NOW - timedelta(days=1),
    )

    changed = service(db_session).fail_stale_runs()

    db_session.expire_all()
    assert changed == 1
    assert old.status is AgentRunStatus.failed
    assert (edge.status, fresh.status) == (AgentRunStatus.running, AgentRunStatus.running)
    assert done.status is AgentRunStatus.succeeded


def test_list_messages_are_oldest_first_limited_to_the_latest_and_need_the_conversation(
    db_session: Session,
) -> None:
    conversation = make_conversation()
    db_session.add(conversation)
    db_session.flush()
    assert conversation.id is not None
    for n in range(5):
        db_session.add(
            make_message(
                conversation.id,
                content=f"tin {n}",
                role=MessageRole.assistant if n % 2 else MessageRole.user,
                created_at=NOW + timedelta(seconds=n),
            )
        )
    db_session.flush()

    everything = service(db_session).list_messages(conversation.id)
    latest = service(db_session).list_messages(conversation.id, limit=2)

    assert [m.content for m in everything] == [f"tin {n}" for n in range(5)]
    assert [m.content for m in latest] == ["tin 3", "tin 4"]
    with pytest.raises(NotFound):
        service(db_session).list_messages(999_999)
