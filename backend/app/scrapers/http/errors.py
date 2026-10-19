"""Lỗi của Fetcher (docs/06 §3). Scraper và pipeline bắt `FetchError` để tính vào `items_failed`."""


class FetchError(Exception):
    """Gốc của mọi lỗi khi tải trang; `url` là URL gây lỗi."""

    def __init__(self, message: str, *, url: str) -> None:
        super().__init__(message)
        self.url = url


class RobotsDisallowed(FetchError):
    """robots.txt không cho phép URL này (không gửi request tới trang)."""


class RobotsUnavailable(RobotsDisallowed):
    """Không tải được robots.txt (lỗi mạng, 5xx): coi như không cho phép, thử lại sau."""


class OfflineModeError(FetchError):
    """`SCRAPER_OFFLINE_ONLY=true` nên không được truy cập domain ngoài mock-shop."""


class RedirectError(FetchError):
    """Chuyển hướng ra ngoài domain, sang scheme lạ, vòng lặp hoặc quá nhiều lần."""


class HttpStatusError(FetchError):
    """Mã 4xx/5xx không phải 403/429 (ví dụ 404, 410) hoặc 3xx không có `Location`."""

    def __init__(self, message: str, *, url: str, status: int) -> None:
        super().__init__(message, url=url)
        self.status = status


class FormNotAllowed(FetchError):
    """Gửi form (đáp án captcha) chỉ được phép tới mock-shop; trang thật không bao giờ nhận."""


class FetchFailed(FetchError):
    """Hết lượt retry vì lỗi mạng, timeout hoặc 5xx."""
