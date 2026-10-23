"""Gửi thông báo giá qua SMTP (đồng bộ, `smtplib`)."""

import smtplib
import ssl
from email.message import EmailMessage

from pydantic import SecretStr

from app.services.notifier.base import NotificationFailed

SMTP_SSL_PORT = 465  # cổng này nói TLS ngay từ đầu; các cổng khác (587, 25) dùng STARTTLS
SEND_TIMEOUT_SECONDS = 15


class EmailNotifier:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        user: str = "",
        password: SecretStr | None = None,
        timeout: float = SEND_TIMEOUT_SECONDS,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._user = user
        self._password = password or SecretStr("")
        self._timeout = timeout

    def send(self, destination: str, subject: str, body: str) -> None:
        try:
            message = EmailMessage()
            message["From"] = self._sender
            message["To"] = destination
            message["Subject"] = subject  # ValueError nếu chứa CR/LF (chống chèn header)
            message.set_content(body)
            context = ssl.create_default_context()
            if self._port == SMTP_SSL_PORT:
                with smtplib.SMTP_SSL(
                    self._host, self._port, timeout=self._timeout, context=context
                ) as smtp:
                    self._deliver(smtp, message)
            else:
                with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                    smtp.starttls(context=context)
                    self._deliver(smtp, message)
        except (smtplib.SMTPException, OSError, ValueError) as error:
            # Chỉ nêu loại lỗi: thông điệp gốc có thể chứa tên người dùng hoặc địa chỉ nhận.
            raise NotificationFailed(f"Không gửi được email ({type(error).__name__})") from None

    def _deliver(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self._user:
            smtp.login(self._user, self._password.get_secret_value())
        smtp.send_message(message)
