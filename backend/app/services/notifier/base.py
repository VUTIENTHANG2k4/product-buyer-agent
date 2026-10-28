"""Giao diện chung của bộ gửi thông báo giá (docs/03 §4)."""

from typing import Protocol


class NotificationFailed(Exception):
    """Gửi thất bại (mạng, xác thực, nơi nhận bị từ chối). Thông điệp không chứa bí mật.

    `channel_down`: lỗi của cả kênh (không kết nối được, hết thời gian chờ, sai tài khoản), không
    riêng một nơi nhận; bộ đánh giá bỏ qua các cảnh báo còn lại của kênh trong cùng một lượt.
    """

    def __init__(self, message: str, *, channel_down: bool = False) -> None:
        super().__init__(message)
        self.channel_down = channel_down


class Notifier(Protocol):
    """Gửi một thông báo tới `destination` (email hoặc Telegram chat id). Đồng bộ, có timeout.

    Ném `NotificationFailed` khi không gửi được.
    """

    def send(self, destination: str, subject: str, body: str) -> None: ...
