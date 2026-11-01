"""Cảnh báo giá (docs/07 §3.5)."""

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.api.deps import AlertServiceDep, NotifiersDep, TestSendLimiterDep
from app.api.errors import error_responses
from app.api.schemas import AlertPatch, AlertsResponse, AlertTestResponse
from app.domain.catalog import AlertCreate, AlertView
from app.domain.enums import AlertStatus

router = APIRouter(tags=["alerts"])

AlertId = Annotated[int, Path(description="Id cảnh báo; id không tồn tại hoặc ngoài miền → 404")]


@router.get(
    "/alerts",
    response_model=AlertsResponse,
    summary="Các cảnh báo giá, mới nhất trước",
    responses=error_responses(422),
)
def list_alerts(service: AlertServiceDep, status: AlertStatus | None = None) -> AlertsResponse:
    return AlertsResponse(items=service.list_alerts(status))


@router.post(
    "/alerts",
    response_model=AlertView,
    status_code=status.HTTP_201_CREATED,
    summary="Đặt cảnh báo giá",
    description=(
        "Thiếu `channel` hoặc `destination` thì lấy mặc định từ cấu hình "
        "(`ALERT_DEFAULT_CHANNEL`, `ALERT_DEFAULT_EMAIL`, `TELEGRAM_CHAT_ID`)."
    ),
    responses=error_responses(404, 409, 422),
)
def create_alert(body: AlertCreate, service: AlertServiceDep) -> AlertView:
    return service.create(body)


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertView,
    summary="Đổi ngưỡng hoặc tạm dừng/bật lại cảnh báo",
    responses=error_responses(404, 409, 422),
)
def update_alert(alert_id: AlertId, body: AlertPatch, service: AlertServiceDep) -> AlertView:
    new_status = None if body.status is None else AlertStatus(body.status)
    return service.update(alert_id, target_price=body.target_price, status=new_status)


@router.delete(
    "/alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa cảnh báo",
    responses=error_responses(404, 422),
)
def delete_alert(alert_id: AlertId, service: AlertServiceDep) -> Response:
    service.delete(alert_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/alerts/{alert_id}/test",
    response_model=AlertTestResponse,
    summary="Gửi thông báo thử tới kênh đã cấu hình",
    description=(
        "Gửi thật một tin nhắn thử tới kênh và nơi nhận của cảnh báo, "
        "không đổi trạng thái cảnh báo. Kênh chưa cấu hình trong `.env` hoặc gửi lỗi thì trả "
        "`sent: false` kèm `reason`. Mỗi cảnh báo chỉ gửi thử lại sau 10 giây (gọi sớm hơn cũng "
        "trả `sent: false`, không gửi)."
    ),
    responses=error_responses(404, 422),
)
def test_alert(
    alert_id: AlertId,
    service: AlertServiceDep,
    notifiers: NotifiersDep,
    limiter: TestSendLimiterDep,
) -> AlertTestResponse:
    result = service.send_test(alert_id, notifiers, limiter)
    return AlertTestResponse(sent=result.sent, reason=result.reason)
