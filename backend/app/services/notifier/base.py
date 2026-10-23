"""Giao diện chung của bộ gửi thông báo giá (docs/03 §4)."""

from typing import Protocol


class NotificationFailed(Exception):
    """Gửi thất bại (mạng, xác thực, nơi nhận bị từ chối). Thông điệp không chứa bí mật."""


class Notifier(Protocol):
    """Gửi một thông báo tới `destination` (email hoặc Telegram chat id). Đồng bộ, có timeout.

    Ném `NotificationFailed` khi không gửi được.
    """

    def send(self, destination: str, subject: str, body: str) -> None: ...
