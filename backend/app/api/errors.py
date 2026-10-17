"""Chuyển mọi lỗi thành `{"error": {"code", "message", "details"}}` (docs/07 §1–2)."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.schemas import ErrorResponse
from app.domain.errors import AppError, InternalError, MethodNotAllowed, NotFound, ValidationFailed

logger = logging.getLogger(__name__)

# Mã chung cho lỗi HTTP do framework sinh (route lạ, sai phương thức).
_FRAMEWORK_ERRORS: dict[int, type[AppError]] = {
    NotFound.status_code: NotFound,
    MethodNotAllowed.status_code: MethodNotAllowed,
}
_GENERIC_HTTP_MESSAGE = "Yêu cầu không hợp lệ."
# RFC 9110: hai mã này không được có thân phản hồi.
_NO_BODY_STATUSES = {204, 304}

_RESPONSE_DESCRIPTIONS = {
    400: "Yêu cầu hoặc đáp án không hợp lệ",
    404: "Không tìm thấy",
    409: "Xung đột trạng thái",
    422: "Dữ liệu gửi lên không hợp lệ",
    500: "Lỗi máy chủ",
    503: "Dịch vụ tạm thời không khả dụng",
}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Khai báo `responses=` để OpenAPI mô tả thân lỗi chuẩn (thay schema 422 mặc định)."""
    return {
        status: {
            "model": ErrorResponse,
            "description": _RESPONSE_DESCRIPTIONS.get(status, "Lỗi"),
        }
        for status in statuses
    }


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return JSONResponse(body, status_code=status_code, headers=headers)


def _standard_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return ""


def _validation_details(exc: RequestValidationError) -> dict[str, Any]:
    """Chỉ giữ vị trí, loại lỗi và câu mô tả; không trả lại `input`/`ctx` của pydantic.

    `message` do pydantic sinh nên một số loại lỗi (uuid, value_error) có thể nhắc một phần
    giá trị; giao diện nên dựa vào `type`.
    """
    items = []
    for error in exc.errors():
        location = error["loc"]
        # JSON sai cú pháp: phần tử cuối của `loc` là vị trí ký tự lỗi, không phải tên trường.
        field_path = () if error["type"] == "json_invalid" else location[1:]
        items.append(
            {
                "in": str(location[0]) if location else "body",
                "field": ".".join(str(part) for part in field_path),
                "message": error["msg"],
                "type": error["type"],
            }
        )
    return {"errors": items}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code in _NO_BODY_STATUSES:
            return Response(status_code=exc.status_code, headers=exc.headers)
        detail = exc.detail
        # Starlette đặt `detail` = cụm chuẩn ("Not Found"); chỉ khi code ném câu riêng mới giữ lại.
        custom = (
            detail
            if isinstance(detail, str) and detail != _standard_phrase(exc.status_code)
            else ""
        )
        known = _FRAMEWORK_ERRORS.get(exc.status_code)
        if known is not None:
            code, message = known.code, custom or known.default_message
        else:
            code = f"HTTP_{exc.status_code}"
            message = detail if isinstance(detail, str) and detail else _GENERIC_HTTP_MESSAGE
        return _error_response(
            exc.status_code, code, message, headers=dict(exc.headers) if exc.headers else None
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            ValidationFailed.status_code,
            ValidationFailed.code,
            ValidationFailed.default_message,
            _validation_details(exc),
        )


class UnhandledErrorMiddleware:
    """Bắt lỗi không lường trước và trả 500 chuẩn.

    Phải nằm **trong** CORSMiddleware (thêm trước nó): `exception_handler(Exception)` chạy
    ngoài CORS nên response 500 sẽ mất header CORS và trình duyệt không đọc được thân lỗi.
    Viết bằng ASGI thuần (không dùng BaseHTTPMiddleware) để không làm hỏng SSE. Lỗi xảy ra
    sau khi response đã bắt đầu thì ném lại vì không thể đổi status nữa.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started:
                raise
            logger.error(
                "Lỗi không xử lý ở %s %s: %s",
                scope.get("method"),
                scope.get("path"),
                type(exc).__name__,
                exc_info=exc,
            )
            response = _error_response(
                InternalError.status_code, InternalError.code, InternalError.default_message
            )
            await response(scope, receive, send)
