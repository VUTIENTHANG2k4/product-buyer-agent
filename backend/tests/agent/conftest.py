"""Fixture cho test tool/agent: ToolContext chạy trên transaction của `db_session`."""

import json
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest
from langchain_core.tools import BaseTool
from sqlmodel import Session

from app.agent.runner import AgentRunner
from app.agent.testing import ScriptedChatModel
from app.agent.tools import ToolContext, build_tools
from scripts.seed import seed_database
from tests.service_support import NOW, clock, make_settings


@pytest.fixture
def tool_ctx(db_session: Session) -> ToolContext:
    """Mỗi lần gọi tool mở một Session mới trên cùng connection/transaction của test.

    `create_savepoint` làm `commit()` của tool chỉ giải phóng savepoint, nên dữ liệu tool ghi
    thấy được trong `db_session` và bị rollback khi test kết thúc.
    """

    def factory() -> Session:
        return Session(bind=db_session.get_bind(), join_transaction_mode="create_savepoint")

    return ToolContext(session_factory=factory, settings=make_settings(), now=clock)


@pytest.fixture
def tools(tool_ctx: ToolContext) -> dict[str, BaseTool]:
    return {tool.name: tool for tool in build_tools(tool_ctx)}


@pytest.fixture
def seeded(db_session: Session) -> Session:
    """Seed `dev` (≥ 30 laptop, phụ kiện, lịch sử giá) với "hiện tại" là NOW."""
    seed_database(db_session, "dev", now=NOW)
    return db_session


class RunnerParts(NamedTuple):
    runner: AgentRunner
    planner: ScriptedChatModel
    executor: ScriptedChatModel


@pytest.fixture
def make_runner(tool_ctx: ToolContext) -> Callable[..., RunnerParts]:
    """Dựng `AgentRunner` với planner/executor là `ScriptedChatModel` có kịch bản cho trước."""

    def build(
        planner_script: list[Any], executor_script: list[Any], *, max_steps: int = 8
    ) -> RunnerParts:
        planner = ScriptedChatModel(script=planner_script)
        executor = ScriptedChatModel(script=executor_script)
        runner = AgentRunner(
            tool_ctx.session_factory,
            make_settings(agent_max_steps=max_steps),
            planner_model=planner,
            executor_model=executor,
            now=clock,
        )
        return RunnerParts(runner, planner, executor)

    return build


async def collect(
    runner: AgentRunner, message: str, conversation_id: int | None = None
) -> list[Any]:
    return [event async for event in runner.run(message, conversation_id)]


def names(events: list[Any]) -> list[str]:
    return [event.name for event in events]


async def call(tools: dict[str, BaseTool], name: str, **args: Any) -> dict[str, Any]:
    """Gọi tool như executor (qua `ainvoke`) và đọc kết quả JSON."""
    raw = await tools[name].ainvoke(args)
    parsed: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
    return parsed


def size(result: dict[str, Any]) -> int:
    return len(json.dumps(result, ensure_ascii=False))
