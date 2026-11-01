"""T7.6: GET /chat/{id} chịu sự kiện và ý định lưu hỏng; SSE trả 404 cho lượt không có."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_session_factory
from app.domain.enums import AgentRunStatus
from tests.factories import make_agent_run, make_conversation


def make_run(session: Session, events: list[Any], **overrides: Any):  # type: ignore[no-untyped-def]
    conversation = make_conversation()
    session.add(conversation)
    session.flush()
    assert conversation.id is not None
    run = make_agent_run(conversation.id, events=events, **overrides)
    session.add(run)
    session.flush()
    return run


@pytest.mark.parametrize(
    "bad",
    [
        "không phải object",
        42,
        None,
        {"event": "final"},  # thiếu data
        {"event": "final", "data": "x"},
        {"event": "final", "data": {"text": 5}},  # sai kiểu
        {"event": "error", "data": []},
        {"event": 7, "data": {}},
        {"event": "clarification", "data": "x"},
    ],
)
def test_get_run_skips_corrupt_events_and_keeps_the_valid_ones(
    client: TestClient, db_session: Session, bad: Any
) -> None:
    good = {"event": "clarification", "data": {"question": "Ngân sách bao nhiêu?"}}
    run = make_run(db_session, [bad, good, bad], status=AgentRunStatus.needs_clarification)

    response = client.get(f"/api/chat/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["clarification"] == "Ngân sách bao nhiêu?"
    assert body["final"] is None and body["error"] is None


def test_get_run_ignores_a_corrupt_stored_intent(client: TestClient, db_session: Session) -> None:
    run = make_run(db_session, [], intent={"category": "không-có-nhóm-này"})

    response = client.get(f"/api/chat/{run.id}")

    assert response.status_code == 200 and response.json()["intent"] is None


def use_session_factory(client: TestClient, db_session: Session) -> None:
    bind = db_session.get_bind()
    client.app.dependency_overrides[get_session_factory] = lambda: (  # type: ignore[attr-defined]
        lambda: Session(bind=bind, join_transaction_mode="create_savepoint")
    )


def test_the_sse_endpoint_returns_404_for_an_unknown_run(
    client: TestClient, db_session: Session
) -> None:
    use_session_factory(client, db_session)

    response = client.get(f"/api/chat/{uuid.uuid4()}/events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_the_sse_stream_skips_a_corrupt_event_but_keeps_the_ids_of_the_others(
    client: TestClient, db_session: Session
) -> None:
    use_session_factory(client, db_session)
    events = [
        {"event": "plan", "data": {"n": 1}},
        "hỏng",
        {"event": "clarification", "data": {"question": "Ngân sách?"}},
    ]
    run = make_run(db_session, events, status=AgentRunStatus.needs_clarification)

    response = client.get(f"/api/chat/{run.id}/events")

    assert response.status_code == 200
    ids = [line for line in response.text.splitlines() if line.startswith("id:")]
    assert [line.split(":", 1)[1].strip() for line in ids] == ["0", "2"]
