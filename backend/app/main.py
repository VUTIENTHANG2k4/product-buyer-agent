"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import UnhandledErrorMiddleware, error_responses, register_error_handlers
from app.api.routers import admin, alerts, categories, health, lists, products
from app.api.tasks import TaskRegistry

FRONTEND_ORIGIN = "http://localhost:5173"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Không đụng CSDL hay mạng lúc khởi động; khi tắt thì hủy tác vụ nền và đóng Fetcher."""
    yield
    await app.state.tasks.cancel_all()
    runtime = getattr(app.state, "scrape_runtime", None)
    if runtime is not None:
        await runtime.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=lifespan,
        title="Product Buyer Agent API",
        version=__version__,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        # Mọi route kế thừa schema lỗi chuẩn (thay HTTPValidationError mặc định của FastAPI).
        responses=error_responses(422, 500),
    )
    app.state.tasks = TaskRegistry()
    register_error_handlers(app)
    # Thứ tự quan trọng: middleware thêm sau nằm ngoài. Bắt lỗi 500 ở lớp trong CORS
    # để response lỗi vẫn có header CORS.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(products.router)
    api.include_router(categories.router)
    api.include_router(lists.router)
    api.include_router(alerts.router)
    api.include_router(admin.router)
    app.include_router(api)
    return app


app = create_app()
