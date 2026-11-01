"""API chat: POST /chat, SSE /chat/{id}/events, /chat/{id}, /conversations (docs/07 §3.2).

Agent chạy bằng `ScriptedChatModel` trên DB test. Tác vụ nền của API chạy trên event loop của
TestClient; `settle` chờ chúng xong trước khi test chạm DB tiếp (chung một connection), nên các
test SSE đọc phần phát lại sau khi lượt đã xong. Logic chờ sự kiện mới của lượt đang chạy được
kiểm riêng ở `tests/unit/test_sse_follow_t72.py`.
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.agent.runner import AgentRunner
from app.agent.testing import ScriptedChatModel, tool_call_message
from app.api.deps import get_agent_runner, get_session, get_session_factory
from app.api.tasks import TaskRegistry
from app.config import get_settings
from app.db.models import AgentRun, ShoppingListItem
from app.domain.enums import AgentRunStatus
from app.main import create_app
from tests.agent.test_runner import (
    LAPTOP_INTENT,
    SEARCH,
    final_call,
    ids,
    make_laptops,
)
from tests.factories import make_conversation
from tests.service_support import NOW, clock, make_settings
from tests.sse_support import parse_sse

INT4_OVER = 2**31
QUESTION = "tìm laptop dưới 30 triệu"


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def tasks_of(client: TestClient) -> TaskRegistry:
    registry: TaskRegistry = cast(FastAPI, client.app).state.tasks
    return registry


def settle(client: TestClient) -> None:
    assert client.portal is not None
    client.portal.call(tasks_of(client).wait_all)


@contextmanager
def chat_client(
    db_session: Session, planner: list[Any], executor: list[Any]
) -> Iterator[TestClient]:
    bind = db_session.get_bind()

    def factory() -> Session:
        return Session(bind=bind, join_transaction_mode="create_savepoint")

    settings = make_settings()
    runner = AgentRunner(
        factory,
        settings,
        planner_model=ScriptedChatModel(script=planner),
        executor_model=ScriptedChatModel(script=executor),
        now=clock,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_agent_runner] = lambda: runner
    with TestClient(app) as client:
        yield client


def ask(client: TestClient, message: str = QUESTION, **body: Any) -> dict[str, Any]:
    response = client.post("/api/chat", json={"message": message, **body})
    assert response.status_code == 202, response.text
    settle(client)
    accepted: dict[str, Any] = response.json()
    return accepted


def stream(client: TestClient, run_id: str, **headers: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/chat/{run_id}/events", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


# ---- luồng chuẩn ----
def test_chat_streams_plan_tool_and_final_events_with_a_table_built_from_the_database(
    db_session: Session,
) -> None:
    products = make_laptops(db_session)
    wanted = ids(products)[:2]
    script = [SEARCH, final_call(product_ids=wanted, follow_up_suggestions=["So sánh 2 máy"])]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        accepted = ask(client)

        events = stream(client, accepted["run_id"])

    assert [e["event"] for e in events] == ["plan", "tool_start", "tool_end", "final"]
    assert [e["id"] for e in events] == ["0", "1", "2", "3"]
    plan, start, end, final = (e["data"] for e in events)
    assert plan["intent"]["category"] == "laptop"
    assert plan["steps"] == LAPTOP_INTENT["plan_steps"]
    assert start["tool"] == "search_catalog" and start["call_id"] == end["call_id"] == "c1"
    assert end["ok"] is True and end["summary"] == "Tìm thấy 3 sản phẩm"
    assert [row["product_id"] for row in final["table"]] == wanted
    assert [row["min_price"] for row in final["table"]] == [20_000_000, 25_000_000]
    assert final["suggestions"] == ["So sánh 2 máy"]
    assert final["data_as_of"].startswith(NOW.strftime("%Y-%m-%dT%H:%M"))


def test_events_can_be_replayed_any_number_of_times_and_resumed_after_last_event_id(
    db_session: Session,
) -> None:
    products = make_laptops(db_session)
    script = [SEARCH, final_call(product_ids=ids(products)[:1])]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        run_id = ask(client)["run_id"]

        first = stream(client, run_id)
        again = stream(client, run_id)
        rest = stream(client, run_id, **{"Last-Event-ID": "1"})
        nothing = stream(client, run_id, **{"Last-Event-ID": "3"})

    assert first == again
    assert [e["id"] for e in rest] == ["2", "3"]
    assert [e["event"] for e in rest] == ["tool_end", "final"]
    assert nothing == []


def test_get_run_returns_status_intent_and_final_result(db_session: Session) -> None:
    products = make_laptops(db_session)
    script = [SEARCH, final_call(product_ids=ids(products)[:2])]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        accepted = ask(client)

        body = client.get(f"/api/chat/{accepted['run_id']}").json()

    assert body["status"] == "succeeded"
    assert body["conversation_id"] == accepted["conversation_id"]
    assert body["intent"]["category"] == "laptop"
    assert [row["product_id"] for row in body["final"]["table"]] == ids(products)[:2]
    assert body["clarification"] is None and body["error"] is None


def test_clarification_ends_the_stream_and_is_reported_by_get_run(db_session: Session) -> None:
    planner = [{"needs_clarification": True, "clarification_question": "Bạn cần gì?"}]
    with chat_client(db_session, planner, []) as client:
        accepted = ask(client, "tìm cái nào rẻ rẻ")

        events = stream(client, accepted["run_id"])
        body = client.get(f"/api/chat/{accepted['run_id']}").json()

    assert [e["event"] for e in events] == ["plan", "clarification"]
    assert events[1]["data"] == {"question": "Bạn cần gì?"}
    assert body["status"] == "needs_clarification"
    assert body["clarification"] == "Bạn cần gì?" and body["final"] is None


def test_invented_product_ids_become_a_hallucination_error_event(db_session: Session) -> None:
    make_laptops(db_session)
    script = [SEARCH, final_call(product_ids=[424_242])]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        accepted = ask(client)

        events = stream(client, accepted["run_id"])
        body = client.get(f"/api/chat/{accepted['run_id']}").json()

    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "AGENT_HALLUCINATION"
    assert body["status"] == "failed"
    assert body["error"]["code"] == "AGENT_HALLUCINATION" and body["final"] is None


def test_planner_failure_is_an_error_event_not_an_http_error(db_session: Session) -> None:
    with chat_client(db_session, [TimeoutError("quá hạn")], []) as client:
        accepted = ask(client)

        events = stream(client, accepted["run_id"])

    assert [e["event"] for e in events] == ["error"]
    assert events[0]["data"]["code"] == "LLM_UNAVAILABLE"


# ---- hội thoại ----
def test_follow_up_in_the_same_conversation_appends_messages_in_order(
    db_session: Session,
) -> None:
    products = make_laptops(db_session)
    planner = [LAPTOP_INTENT, LAPTOP_INTENT]
    script = [
        SEARCH,
        final_call(text="Lượt một.", product_ids=ids(products)[:1]),
        SEARCH,
        final_call(text="Lượt hai.", product_ids=ids(products)[1:2]),
    ]
    with chat_client(db_session, planner, script) as client:
        first = ask(client, "tìm laptop")
        second = ask(client, "còn máy nào nữa", conversation_id=first["conversation_id"])

        messages = client.get(f"/api/conversations/{first['conversation_id']}/messages").json()
        conversations = client.get("/api/conversations").json()

    assert second["conversation_id"] == first["conversation_id"]
    assert second["run_id"] != first["run_id"]
    assert [(m["role"], m["content"]) for m in messages["items"]] == [
        ("user", "tìm laptop"),
        ("assistant", "Lượt một."),
        ("user", "còn máy nào nữa"),
        ("assistant", "Lượt hai."),
    ]
    assert messages["items"][1]["payload"] == {"product_ids": ids(products)[:1]}
    assert [c["conversation_id"] for c in conversations["items"]] == [first["conversation_id"]]
    assert conversations["items"][0]["title"] == "tìm laptop"


def test_conversations_are_listed_newest_first_with_a_limit(db_session: Session) -> None:
    older = make_conversation(title="Cũ", created_at=NOW - timedelta(days=2))
    newer = make_conversation(title="Mới", created_at=NOW - timedelta(days=1))
    db_session.add_all([older, newer])
    db_session.flush()
    with chat_client(db_session, [], []) as client:
        both = client.get("/api/conversations").json()["items"]
        one = client.get("/api/conversations", params={"limit": 1}).json()["items"]

    assert [c["title"] for c in both] == ["Mới", "Cũ"]
    assert [c["title"] for c in one] == ["Mới"]


@pytest.mark.parametrize("limit", ["0", "101", "x"])
def test_conversations_reject_a_bad_limit(db_session: Session, limit: str) -> None:
    with chat_client(db_session, [], []) as client:
        assert client.get("/api/conversations", params={"limit": limit}).status_code == 422


@pytest.mark.parametrize("conversation_id", ["999999", "0", "-1", str(INT4_OVER), str(2**70)])
def test_messages_of_an_unknown_or_out_of_range_conversation_is_404(
    db_session: Session, conversation_id: str
) -> None:
    with chat_client(db_session, [], []) as client:
        response = client.get(f"/api/conversations/{conversation_id}/messages")

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


# ---- đầu vào ----
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 1001},
        {"message": "a\x00b"},
        {"message": 5},
        {"message": "ok", "conversation_id": "abc"},
    ],
)
def test_chat_rejects_bad_messages_without_starting_a_run(
    db_session: Session, payload: dict[str, Any]
) -> None:
    with chat_client(db_session, [LAPTOP_INTENT], []) as client:
        response = client.post("/api/chat", json=payload)

        assert response.status_code == 422
        assert error_code(response) == "VALIDATION_ERROR"
        assert tasks_of(client).pending == 0
    assert db_session.exec(select(AgentRun)).all() == []


@pytest.mark.parametrize("conversation_id", [999_999, 0, INT4_OVER, 2**70])
def test_chat_in_an_unknown_conversation_is_404(db_session: Session, conversation_id: int) -> None:
    with chat_client(db_session, [LAPTOP_INTENT], []) as client:
        response = client.post(
            "/api/chat", json={"message": "xin chào", "conversation_id": conversation_id}
        )

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_message_of_exactly_1000_characters_is_accepted(db_session: Session) -> None:
    planner = [{"needs_clarification": True, "clarification_question": "Bạn cần gì?"}]
    with chat_client(db_session, planner, []) as client:
        response = client.post("/api/chat", json={"message": "a" * 1000})
        settle(client)

    assert response.status_code == 202


def test_chat_without_a_configured_llm_key_is_503_llm_unavailable(db_session: Session) -> None:
    bind = db_session.get_bind()
    settings = make_settings(llm_provider="gemini", google_api_key="")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session_factory] = lambda: (
        lambda: Session(bind=bind, join_transaction_mode="create_savepoint")
    )
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "xin chào"})

    assert response.status_code == 503
    assert error_code(response) == "LLM_UNAVAILABLE"
    assert db_session.exec(select(AgentRun)).all() == []


@pytest.mark.parametrize("path", ["/api/chat/{id}", "/api/chat/{id}/events"])
def test_unknown_run_id_is_404_run_not_found(db_session: Session, path: str) -> None:
    with chat_client(db_session, [], []) as client:
        response = client.get(path.format(id=uuid.uuid4()))

    assert response.status_code == 404
    assert error_code(response) == "RUN_NOT_FOUND"


@pytest.mark.parametrize("path", ["/api/chat/abc", "/api/chat/abc/events", "/api/chat/123"])
def test_malformed_run_id_is_validation_error(db_session: Session, path: str) -> None:
    with chat_client(db_session, [], []) as client:
        assert client.get(path).status_code == 422


def test_last_event_id_must_be_a_number(db_session: Session) -> None:
    make_laptops(db_session)
    script = [SEARCH, final_call(product_ids=[])]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        run_id = ask(client)["run_id"]

        response = client.get(f"/api/chat/{run_id}/events", headers={"Last-Event-ID": "abc"})

    assert response.status_code == 422


# ---- tool ghi qua chat ----
def test_chat_adds_to_the_list_only_when_the_message_asks_for_it(db_session: Session) -> None:
    products = make_laptops(db_session)
    first_id = ids(products)[0]
    add = tool_call_message("add_to_shopping_list", {"product_id": first_id}, "c2")
    script = [SEARCH, add, final_call(product_ids=[first_id])]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        ask(client, "tìm laptop rồi thêm máy rẻ nhất vào danh sách")

    db_session.expire_all()
    assert [item.product_id for item in db_session.exec(select(ShoppingListItem))] == [first_id]


@pytest.mark.parametrize(
    "message", ["tìm laptop dưới 30 triệu", "đừng thêm vào danh sách, chỉ cho tôi xem"]
)
def test_chat_does_not_write_when_the_message_does_not_request_it(
    db_session: Session, message: str
) -> None:
    products = make_laptops(db_session)
    add = tool_call_message("add_to_shopping_list", {"product_id": ids(products)[0]}, "c2")
    script = [SEARCH, add, add, {"text": "Chưa thêm."}]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        accepted = ask(client, message)

        events = stream(client, accepted["run_id"])

    db_session.expire_all()
    assert db_session.exec(select(ShoppingListItem)).all() == []
    ends = [e["data"] for e in events if e["event"] == "tool_end"]
    assert [e["ok"] for e in ends] == [True, False, False]


# ---- lượt kẹt ----
def test_a_run_stuck_in_running_is_marked_failed_by_the_next_chat(db_session: Session) -> None:
    conversation = make_conversation(created_at=NOW - timedelta(hours=2))
    db_session.add(conversation)
    db_session.flush()
    assert conversation.id is not None
    stuck = AgentRun(
        conversation_id=conversation.id,
        status=AgentRunStatus.running,
        created_at=NOW - timedelta(hours=1),
    )
    recent = AgentRun(
        conversation_id=conversation.id,
        status=AgentRunStatus.running,
        created_at=NOW - timedelta(minutes=5),
    )
    db_session.add_all([stuck, recent])
    db_session.flush()
    planner = [{"needs_clarification": True, "clarification_question": "Bạn cần gì?"}]
    with chat_client(db_session, planner, []) as client:
        ask(client, "xin chào")

    db_session.expire_all()
    assert db_session.get(AgentRun, stuck.id).status is AgentRunStatus.failed  # type: ignore[union-attr]
    assert db_session.get(AgentRun, recent.id).status is AgentRunStatus.running  # type: ignore[union-attr]


def test_replaying_a_failed_run_without_a_final_event_ends_instead_of_hanging(
    db_session: Session,
) -> None:
    conversation = make_conversation()
    db_session.add(conversation)
    db_session.flush()
    assert conversation.id is not None
    run = AgentRun(
        conversation_id=conversation.id,
        status=AgentRunStatus.failed,
        events=[{"event": "plan", "data": {"intent": {}, "steps": []}}],
    )
    db_session.add(run)
    db_session.flush()
    with chat_client(db_session, [], []) as client:
        events = stream(client, str(run.id))

    assert [e["event"] for e in events] == ["plan"]


def test_sse_payloads_are_valid_json(db_session: Session) -> None:
    products = make_laptops(db_session)
    script = [SEARCH, final_call(product_ids=ids(products)[:1])]
    with chat_client(db_session, [LAPTOP_INTENT], script) as client:
        run_id = ask(client)["run_id"]
        raw = client.get(f"/api/chat/{run_id}/events").text

    for block in raw.strip().split("\n\n"):
        data_lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        assert json.loads("\n".join(data_lines))
