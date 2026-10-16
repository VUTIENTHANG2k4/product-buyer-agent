"""FastAPI app factory."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routers import health

FRONTEND_ORIGIN = "http://localhost:5173"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Product Buyer Agent API",
        version=__version__,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    app.include_router(api)
    return app


app = create_app()
