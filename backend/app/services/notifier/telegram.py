"""Gửi thông báo giá qua Telegram Bot API (đồng bộ, `httpx.Client`)."""

import logging

import httpx
from pydantic import SecretStr

from app.services.notifier.base import NotificationFailed

# URL gọi API chứa token bot: logger của httpx ở mức INFO sẽ in nó, nên hạ ngay tại nguồn thay vì
# trông chờ từng điểm vào (API, worker, script) tự làm.
logging.getLogger("httpx").setLevel(logging.WARNING)

TELEGRAM_API = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 15
MAX_TEXT_LENGTH = 4096  # giới hạn của sendMessage


class TelegramNotifier:
    def __init__(self, token: SecretStr, *, timeout: float = SEND_TIMEOUT_SECONDS) -> None:
        self._token = token
        self._timeout = timeout

    def send(self, destination: str, subject: str, body: str) -> None:
        text = f"{subject}\n\n{body}"[:MAX_TEXT_LENGTH]
        url = f"{TELEGRAM_API}/bot{self._token.get_secret_value()}/sendMessage"
        try:
            response = httpx.post(
                url, json={"chat_id": destination, "text": text}, timeout=self._timeout
            )
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            # Không đưa thông điệp gốc vào lỗi: `httpx` có thể in cả URL chứa token bot.
            # `InvalidURL` (token có ký tự điều khiển) không thuộc `HTTPError` (BUG-M9-2).
            raise NotificationFailed(f"Không gửi được Telegram ({type(error).__name__})") from None
        if response.status_code != httpx.codes.OK:
            raise NotificationFailed(
                f"Telegram từ chối (HTTP {response.status_code}): {_description(response)}"
            )
        # Telegram luôn trả `{"ok": true, ...}` khi gửi được. HTTP 200 với thân khác (proxy hoặc
        # captive portal trả trang đăng nhập, `ok: false`) không phải là đã gửi (BUG-M9-1): coi là
        # thành công sẽ đưa cảnh báo sang `triggered` dù người dùng không nhận được tin.
        if not _is_ok(response):
            raise NotificationFailed(
                f"Telegram trả HTTP 200 nhưng không xác nhận đã gửi: {_description(response)}"
            )


def _is_ok(response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("ok") is True


def _description(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "không rõ lý do"
    description = payload.get("description") if isinstance(payload, dict) else None
    return description[:200] if isinstance(description, str) else "không rõ lý do"
