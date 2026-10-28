"""Quản trị thu thập: nguồn, lượt chạy, nhập đáp án challenge (docs/07 §3.6)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import AdminServiceDep, ScrapeServiceDep, TaskRegistryDep
from app.api.errors import error_responses
from app.api.schemas import ChallengeAnswer, ScrapeRunCreate, ScrapeRunPage, SourcesResponse
from app.domain.admin import ChallengeAnswered, ChallengeView, ScrapeRunStarted, ScrapeRunView
from app.domain.enums import Category, ScrapeStatus, SiteKey

router = APIRouter(prefix="/admin", tags=["admin"])

RunId = Annotated[int, Path(description="Id lượt thu thập; không tồn tại hoặc ngoài miền → 404")]


@router.get(
    "/sources",
    response_model=SourcesResponse,
    summary="Các trang nguồn, tình trạng robots.txt và lượt chạy gần nhất",
)
def list_sources(service: AdminServiceDep) -> SourcesResponse:
    return SourcesResponse(items=service.sources())


@router.get(
    "/scrape-runs",
    response_model=ScrapeRunPage,
    summary="Các lượt thu thập, mới nhất trước",
    responses=error_responses(422),
)
def list_scrape_runs(
    service: AdminServiceDep,
    site: SiteKey | None = None,
    category: Category | None = None,
    status: ScrapeStatus | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ScrapeRunPage:
    runs, total = service.list_runs(
        site=site, category=category, status=status, page=page, page_size=page_size
    )
    return ScrapeRunPage(items=runs, total=total, page=page, page_size=page_size)


@router.get(
    "/scrape-runs/{run_id}",
    response_model=ScrapeRunView,
    summary="Chi tiết một lượt thu thập: thống kê và lỗi",
    responses=error_responses(404, 422),
)
def get_scrape_run(run_id: RunId, service: AdminServiceDep) -> ScrapeRunView:
    return service.get_run(run_id)


@router.post(
    "/scrape-runs",
    response_model=ScrapeRunStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bắt đầu một lượt thu thập (chạy nền)",
    description=(
        "Trả `run_id` ngay; theo dõi bằng `GET /admin/scrape-runs/{id}`. Trang thật bị từ chối "
        "(`OFFLINE_MODE`) khi `SCRAPER_OFFLINE_ONLY=true`."
    ),
    responses=error_responses(409, 422),
)
async def start_scrape_run(
    body: ScrapeRunCreate, service: ScrapeServiceDep, tasks: TaskRegistryDep
) -> ScrapeRunStarted:
    started = await service.start(body.site, body.category, max_pages=body.max_pages)
    tasks.spawn(service.execute(started), name=f"scrape-run-{started.run_id}")
    return ScrapeRunStarted(run_id=started.run_id)


@router.get(
    "/scrape-runs/{run_id}/challenge",
    response_model=ChallengeView,
    summary="Challenge đang chờ người nhập đáp án",
    responses=error_responses(404, 409, 422),
)
def get_challenge(run_id: RunId, service: ScrapeServiceDep) -> ChallengeView:
    return service.challenge_of(run_id)


@router.delete(
    "/scrape-runs/{run_id}/challenge",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hủy lượt đang chờ đáp án captcha",
    description=(
        "Đóng lượt `NEEDS_HUMAN` thành `FAILED` để lượt mới chạy ngay (hữu ích khi mock-shop đã "
        "reset nên đáp án không còn đúng). Lượt không chờ đáp án → 409 `CHALLENGE_NOT_PENDING`."
    ),
    responses=error_responses(404, 409, 422),
)
async def cancel_challenge(run_id: RunId, service: ScrapeServiceDep) -> Response:
    await service.cancel_challenge(run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/scrape-runs/{run_id}/challenge",
    response_model=ChallengeAnswered,
    summary="Gửi đáp án captcha (chỉ mock-shop) và cho lượt chạy tiếp",
    description="Đáp án đúng: lượt chạy tiếp ở nền. Sai: 400 `CHALLENGE_FAILED`, lượt vẫn chờ.",
    responses=error_responses(400, 404, 409, 422),
)
async def answer_challenge(
    run_id: RunId, body: ChallengeAnswer, service: ScrapeServiceDep, tasks: TaskRegistryDep
) -> ChallengeAnswered:
    started = await service.reopen(run_id, body.answer)
    tasks.spawn(service.execute(started), name=f"scrape-run-{started.run_id}")
    return ChallengeAnswered(status="RUNNING")
