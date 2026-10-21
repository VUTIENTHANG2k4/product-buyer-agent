"""Dependency dùng chung của các router."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlmodel import Session

from app.agent.llm import get_chat_model
from app.agent.runner import AgentRunner
from app.agent.spec_filler import build_spec_filler
from app.api.tasks import TaskRegistry
from app.config import Settings, get_settings
from app.services import health_service
from app.services.admin_service import AdminService
from app.services.alert_service import AlertService
from app.services.catalog_service import CatalogService
from app.services.compare_service import CompareService
from app.services.database import SessionFactory, session_factory, session_scope
from app.services.health_service import DbStatus
from app.services.scrape_runtime import ScrapeRuntime
from app.services.scrape_service import ScrapeService
from app.services.shopping_list_service import ShoppingListService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db_status(settings: SettingsDep) -> DbStatus:
    """Trạng thái kết nối CSDL; test ghi đè dependency này."""
    return health_service.check_db(settings.database_url.get_secret_value())


DbStatusDep = Annotated[DbStatus, Depends(get_db_status)]


def get_session(settings: SettingsDep) -> Iterator[Session]:
    """Một session mỗi request; test ghi đè bằng session của fixture `db_session`."""
    with session_scope(settings.database_url.get_secret_value()) as session:
        yield session


# scope="function": commit chạy ngay sau hàm xử lý, TRƯỚC khi gửi response. Mặc định ("request")
# commit chạy sau khi response đã gửi nên client có thể đọc lại trước khi dữ liệu được lưu.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def get_catalog_service(session: SessionDep) -> CatalogService:
    return CatalogService(session)


def get_compare_service(session: SessionDep) -> CompareService:
    return CompareService(session)


CatalogServiceDep = Annotated[CatalogService, Depends(get_catalog_service)]
CompareServiceDep = Annotated[CompareService, Depends(get_compare_service)]


def get_shopping_list_service(session: SessionDep) -> ShoppingListService:
    return ShoppingListService(session)


def get_alert_service(session: SessionDep, settings: SettingsDep) -> AlertService:
    return AlertService(session, settings)


ShoppingListServiceDep = Annotated[ShoppingListService, Depends(get_shopping_list_service)]
AlertServiceDep = Annotated[AlertService, Depends(get_alert_service)]


def get_task_registry(request: Request) -> TaskRegistry:
    registry: TaskRegistry = request.app.state.tasks
    return registry


async def get_scrape_runtime(request: Request, settings: SettingsDep) -> ScrapeRuntime:
    """Fetcher + ScrapeService dựng ở lần dùng đầu và giữ trên `app.state` (đóng khi tắt app).

    `async def` không `await`: chạy trên event loop nên "kiểm rồi gán" là nguyên tử. Dependency
    đồng bộ chạy trong threadpool, hai request đầu tiên đồng thời sẽ dựng hai Fetcher và làm mất
    giới hạn ≥ 5 giây/domain dùng chung (docs/02 §3).
    """
    runtime: ScrapeRuntime | None = getattr(request.app.state, "scrape_runtime", None)
    if runtime is None:
        runtime = ScrapeRuntime.build(settings, build_spec_filler(settings))
        request.app.state.scrape_runtime = runtime
    return runtime


async def get_scrape_service(
    runtime: Annotated[ScrapeRuntime, Depends(get_scrape_runtime)],
) -> ScrapeService:
    return runtime.service


def get_admin_service(request: Request, session: SessionDep, settings: SettingsDep) -> AdminService:
    runtime: ScrapeRuntime | None = getattr(request.app.state, "scrape_runtime", None)
    return AdminService(
        session, settings, robots=None if runtime is None else runtime.fetcher.robots_snapshot
    )


TaskRegistryDep = Annotated[TaskRegistry, Depends(get_task_registry)]
ScrapeServiceDep = Annotated[ScrapeService, Depends(get_scrape_service)]
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]


def get_session_factory(settings: SettingsDep) -> SessionFactory:
    """Hàm tạo session ngắn hạn cho tác vụ nền và luồng SSE (không gắn với một request)."""
    return session_factory(settings.database_url.get_secret_value())


SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


async def get_agent_runner(
    request: Request, settings: SettingsDep, factory: SessionFactoryDep
) -> AgentRunner:
    """Runner dùng chung, dựng ở lần chat đầu tiên. Thiếu khóa LLM -> `LlmUnavailable` (503)."""
    runner: AgentRunner | None = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        runner = AgentRunner(
            factory,
            settings,
            planner_model=get_chat_model("planner", settings),
            executor_model=get_chat_model("executor", settings),
        )
        request.app.state.agent_runner = runner
    return runner


AgentRunnerDep = Annotated[AgentRunner, Depends(get_agent_runner)]
