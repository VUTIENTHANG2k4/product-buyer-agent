"""Chat với agent: tạo lượt, theo dõi tiến trình bằng SSE, xem lại hội thoại (docs/07 §3.2)."""

import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.agent.schemas import ErrorEvent, FinalEvent
from app.api.deps import AgentRunnerDep, SessionDep, SessionFactoryDep, TaskRegistryDep
from app.api.errors import error_responses, json_error_responses
from app.api.schemas import (
    ChatAccepted,
    ChatRequest,
    ConversationsResponse,
    MessagesResponse,
    RunStatusResponse,
)
from app.api.sse import drain, follow_events
from app.domain.dto import QueryIntent
from app.services.conversation_service import ConversationService, read_run_events, require_run

router = APIRouter(tags=["chat"])

RunId = Annotated[uuid.UUID, Path(description="Id lượt chạy do `POST /chat` trả về")]


def existing_run(run_id: RunId, factory: SessionFactoryDep) -> uuid.UUID:
    """404 `RUN_NOT_FOUND` trước khi mở luồng (sau khi luồng đã mở thì không đổi được status)."""
    require_run(factory, run_id)
    return run_id


@router.post(
    "/chat",
    response_model=ChatAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Gửi một câu cho agent (chạy nền)",
    description=(
        "Trả `run_id` ngay; theo dõi tiến trình ở `GET /chat/{run_id}/events` (SSE) hoặc lấy kết "
        "quả ở `GET /chat/{run_id}`. Bỏ `conversation_id` để mở hội thoại mới."
    ),
    responses=error_responses(404, 422, 503),
)
async def send_message(
    body: ChatRequest, runner: AgentRunnerDep, tasks: TaskRegistryDep
) -> ChatAccepted:
    handle = await runner.start(body.message, body.conversation_id)
    tasks.spawn(drain(runner.stream(handle, body.message.strip())), name=f"chat-{handle.run_id}")
    return ChatAccepted(run_id=handle.run_id, conversation_id=handle.conversation_id)


@router.get(
    "/chat/{run_id}/events",
    response_class=EventSourceResponse,
    summary="Tiến trình của một lượt chạy (SSE)",
    description=(
        "Sự kiện `plan`, `clarification`, `tool_start`, `tool_end`, `final`, `error` (docs/05 §6). "
        "Kết nối sau khi lượt đã xong thì phát lại toàn bộ rồi đóng. Mỗi sự kiện có `id` là vị trí "
        "của nó; gửi `Last-Event-ID` để nhận tiếp từ sau vị trí đó."
    ),
    responses=json_error_responses(404, 422, 500),
)
async def stream_events(
    run_id: Annotated[uuid.UUID, Depends(existing_run)],
    factory: SessionFactoryDep,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    after = 0 if last_event_id is None else last_event_id + 1
    async for position, record in follow_events(
        lambda start: read_run_events(factory, run_id, start), after
    ):
        yield ServerSentEvent(data=record["data"], event=record["event"], id=str(position))


@router.get(
    "/chat/{run_id}",
    response_model=RunStatusResponse,
    summary="Trạng thái và kết quả cuối của một lượt chạy",
    responses=error_responses(404, 422),
)
def get_run(run_id: RunId, session: SessionDep) -> RunStatusResponse:
    run = ConversationService(session).get_run(run_id)
    final = clarification = error = None
    for record in run.events:
        match record.get("event"):
            case "final":
                final = FinalEvent.model_validate(record["data"])
            case "clarification":
                clarification = str(record["data"].get("question", ""))
            case "error":
                error = ErrorEvent.model_validate(record["data"])
    return RunStatusResponse(
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        status=run.status,
        intent=None if run.intent is None else QueryIntent.model_validate(run.intent),
        final=final,
        clarification=clarification,
        error=error,
    )


@router.get(
    "/conversations",
    response_model=ConversationsResponse,
    summary="Các hội thoại gần đây, mới nhất trước",
    responses=error_responses(422),
)
def list_conversations(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> ConversationsResponse:
    return ConversationsResponse(items=ConversationService(session).list_conversations(limit))


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
    summary="Tin nhắn của một hội thoại, cũ → mới",
    responses=error_responses(404, 422),
)
def list_messages(
    conversation_id: Annotated[int, Path(description="Id hội thoại")], session: SessionDep
) -> MessagesResponse:
    return MessagesResponse(items=ConversationService(session).list_messages(conversation_id))
