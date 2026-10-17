import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.db.repositories.agent_runs import AgentRunRepository
from app.db.repositories.conversations import ConversationRepository, MessageRepository
from app.domain.enums import AgentRunStatus, MessageRole

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _conversation_id(session: Session, title: str | None = "Mock") -> int:
    conversation = ConversationRepository(session).create(title)
    assert conversation.id is not None
    return conversation.id


def test_conversation_create_get_set_title_and_list_recent(db_session: Session) -> None:
    repo = ConversationRepository(db_session)
    first = repo.create(now=T0)
    second = repo.create("Mock hai", now=T0 + timedelta(hours=1))

    assert first.title is None
    assert repo.get(first.id) is first  # type: ignore[arg-type]
    assert repo.get(999_999_999) is None
    assert repo.list_recent() == [second, first]
    assert repo.list_recent(limit=1) == [second]

    repo.set_title(first, "Mock một")
    assert first.title == "Mock một"


def test_delete_conversation_cascades_to_messages_and_runs(db_session: Session) -> None:
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    runs = AgentRunRepository(db_session)
    conversation = conversations.create("Mock")
    conversation_id = conversation.id
    assert conversation_id is not None
    messages.add(conversation_id, MessageRole.user, "xin chào")
    run_id = runs.create(conversation_id).id

    conversations.delete(conversation)

    assert conversations.get(conversation_id) is None
    assert messages.list_for_conversation(conversation_id) == []
    assert runs.get(run_id) is None


def test_add_message_stores_payload_copy(db_session: Session) -> None:
    repo = MessageRepository(db_session)
    conversation_id = _conversation_id(db_session)
    payload = {"product_ids": [12, 31]}

    message = repo.add(conversation_id, MessageRole.assistant, "kết quả", payload=payload, now=T0)
    payload["product_ids"] = []
    db_session.expire(message)

    assert message.id is not None
    assert message.payload == {"product_ids": [12, 31]}
    assert repo.add(conversation_id, MessageRole.user, "hỏi").payload is None


def test_list_for_conversation_is_chronological_and_limit_keeps_the_latest(
    db_session: Session,
) -> None:
    repo = MessageRepository(db_session)
    conversation_id = _conversation_id(db_session)
    other_id = _conversation_id(db_session, "Mock khác")
    for index in range(4):
        repo.add(
            conversation_id, MessageRole.user, f"tin {index}", now=T0 + timedelta(minutes=index)
        )
    repo.add(other_id, MessageRole.user, "của hội thoại khác", now=T0)

    assert [m.content for m in repo.list_for_conversation(conversation_id)] == [
        "tin 0",
        "tin 1",
        "tin 2",
        "tin 3",
    ]
    assert [m.content for m in repo.list_for_conversation(conversation_id, limit=2)] == [
        "tin 2",
        "tin 3",
    ]
    assert repo.list_for_conversation(999_999_999) == []


def test_latest_assistant_payload_skips_user_and_payloadless_messages(db_session: Session) -> None:
    repo = MessageRepository(db_session)
    conversation_id = _conversation_id(db_session)
    assert repo.latest_assistant_payload(conversation_id) is None

    repo.add(conversation_id, MessageRole.assistant, "cũ", payload={"product_ids": [1]}, now=T0)
    repo.add(
        conversation_id,
        MessageRole.assistant,
        "mới",
        payload={"product_ids": [12, 31]},
        now=T0 + timedelta(minutes=1),
    )
    repo.add(conversation_id, MessageRole.assistant, "không payload", now=T0 + timedelta(minutes=2))
    repo.add(
        conversation_id,
        MessageRole.user,
        "user",
        payload={"product_ids": [99]},
        now=T0 + timedelta(minutes=3),
    )

    assert repo.latest_assistant_payload(conversation_id) == {"product_ids": [12, 31]}


def test_agent_run_lifecycle_keeps_events_in_order(db_session: Session) -> None:
    repo = AgentRunRepository(db_session)
    conversation_id = _conversation_id(db_session)
    run = repo.create(conversation_id, now=T0)

    assert isinstance(run.id, uuid.UUID)
    assert (run.status, run.events, run.tool_calls) == (AgentRunStatus.running, [], 0)
    assert repo.get(run.id) is run
    assert repo.get(uuid.uuid4()) is None

    repo.set_intent(run, {"category": "laptop", "limit": 10})
    repo.append_event(run, {"type": "plan", "steps": ["a"]})
    repo.append_event(run, {"type": "tool_start", "name": "search_catalog"})
    repo.append_event(run, {"type": "final", "text": "xong"})
    repo.finish(run, AgentRunStatus.succeeded, tool_calls=1, latency_ms=840)
    db_session.expire(run)

    assert run.status == AgentRunStatus.succeeded
    assert run.intent == {"category": "laptop", "limit": 10}
    assert [event["type"] for event in run.events] == ["plan", "tool_start", "final"]
    assert (run.tool_calls, run.latency_ms) == (1, 840)


def test_agent_run_create_with_explicit_id_and_finish_without_metrics(db_session: Session) -> None:
    repo = AgentRunRepository(db_session)
    run_id = uuid.uuid4()
    run = repo.create(_conversation_id(db_session), run_id=run_id)

    repo.finish(run, AgentRunStatus.needs_clarification)

    assert run.id == run_id
    assert run.status == AgentRunStatus.needs_clarification
    assert (run.tool_calls, run.latency_ms) == (0, None)


def test_list_runs_for_conversation_oldest_first(db_session: Session) -> None:
    repo = AgentRunRepository(db_session)
    conversation_id = _conversation_id(db_session)
    other_id = _conversation_id(db_session, "Mock khác")
    late = repo.create(conversation_id, now=T0 + timedelta(minutes=5))
    early = repo.create(conversation_id, now=T0)
    repo.create(other_id, now=T0)

    assert repo.list_for_conversation(conversation_id) == [early, late]
