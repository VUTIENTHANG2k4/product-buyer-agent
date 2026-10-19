"""Lỗi nghiệp vụ: mỗi lớp ứng với một mã HTTP trong docs/07 §2.

Handler ở `app/api/errors.py` chuyển chúng thành `{"error": {"code", "message", "details"}}`.
`AGENT_HALLUCINATION` và `AGENT_STEP_LIMIT` chỉ xuất hiện trong sự kiện SSE `error` nên
không có lớp ở đây.
"""

from typing import Any, ClassVar


class AppError(Exception):
    """Gốc của lỗi nghiệp vụ. Lớp con khai báo `code`, `status_code`, `default_message`."""

    code: ClassVar[str]
    status_code: ClassVar[int]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None):
        self.message = message or self.default_message
        self.details: dict[str, Any] = dict(details) if details else {}
        super().__init__(self.message)


class ValidationFailed(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422
    default_message = "Dữ liệu gửi lên không hợp lệ."


class InvalidScrapeRequest(ValidationFailed, ValueError):
    """Yêu cầu thu thập sai (`max_pages` < 1, nhóm không thuộc trang...). Vừa là `ValueError`."""


class NotFound(AppError):
    code = "NOT_FOUND"
    status_code = 404
    default_message = "Không tìm thấy tài nguyên yêu cầu."


class MethodNotAllowed(AppError):
    code = "METHOD_NOT_ALLOWED"
    status_code = 405
    default_message = "Phương thức không được hỗ trợ cho đường dẫn này."


class ProductNotFound(AppError):
    code = "PRODUCT_NOT_FOUND"
    status_code = 404
    default_message = "Không tìm thấy sản phẩm."


class ListNotFound(AppError):
    code = "LIST_NOT_FOUND"
    status_code = 404
    default_message = "Không tìm thấy danh sách mua."


class AlertNotFound(AppError):
    code = "ALERT_NOT_FOUND"
    status_code = 404
    default_message = "Không tìm thấy cảnh báo giá."


class RunNotFound(AppError):
    code = "RUN_NOT_FOUND"
    status_code = 404
    default_message = "Không tìm thấy lượt chạy."


class DuplicateAlert(AppError):
    code = "DUPLICATE_ALERT"
    status_code = 409
    default_message = "Đã có cảnh báo đang hoạt động cho sản phẩm và ngưỡng giá này."


class ScrapeAlreadyRunning(AppError):
    code = "SCRAPE_ALREADY_RUNNING"
    status_code = 409
    default_message = "Đang có lượt thu thập chạy cho trang và nhóm sản phẩm này."


class SiteCooldown(AppError):
    code = "SITE_COOLDOWN"
    status_code = 409
    default_message = "Trang này đang trong thời gian tạm nghỉ sau khi bị chặn."


class OfflineMode(AppError):
    code = "OFFLINE_MODE"
    status_code = 409
    default_message = "Đang bật chế độ ngoại tuyến nên không thể truy cập trang thật."


class ChallengeNotPending(AppError):
    code = "CHALLENGE_NOT_PENDING"
    status_code = 409
    default_message = "Lượt chạy này không đang chờ đáp án captcha."


class ChallengeFailed(AppError):
    code = "CHALLENGE_FAILED"
    status_code = 400
    default_message = "Đáp án captcha không đúng."


class LlmUnavailable(AppError):
    code = "LLM_UNAVAILABLE"
    status_code = 503
    default_message = "Không gọi được mô hình ngôn ngữ lúc này."


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    status_code = 500
    default_message = "Đã có lỗi xảy ra phía máy chủ."
