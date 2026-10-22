"""Gửi thông báo giá qua Telegram Bot API (đồng bộ, `httpx.Client`)."""

import httpx
from pydantic import SecretStr

from app.services.notifier.base import NotificationFailed

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
        except httpx.HTTPError as error:
            # Không đưa thông điệp gốc vào lỗi: `httpx` có thể in cả URL chứa token bot.
            raise NotificationFailed(f"Không gửi được Telegram ({type(error).__name__})") from None
        if response.status_code != httpx.codes.OK:
            raise NotificationFailed(
                f"Telegram từ chối (HTTP {response.status_code}): {_description(response)}"
            )


def _description(response: httpx.Response) -> str:
    try:
        description = response.json().get("description")
    except ValueError:
        return "không rõ lý do"
    return description[:200] if isinstance(description, str) else "không rõ lý do"
