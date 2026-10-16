from fastapi import APIRouter

from app import __version__
from app.api.deps import DbStatusDep, SettingsDep
from app.api.schemas import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Kiểm tra sức khỏe hệ thống")
def health(settings: SettingsDep, db: DbStatusDep) -> HealthResponse:
    return HealthResponse(
        status="ok" if db == "ok" else "degraded",
        db=db,
        llm_provider=settings.llm_provider,
        offline_mode=settings.scraper_offline_only,
        version=__version__,
    )
