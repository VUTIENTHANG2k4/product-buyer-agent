"""Trạng thái trong bộ nhớ của mock-shop: bộ đếm request, captcha đang chờ, cookie đã xác minh."""

import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bỏ ký tự dễ nhầm (I, O, 0, 1)
CODE_LENGTH = 5
PASS_TTL_SECONDS = 600  # cookie `mock_pass` hết hạn sau 10 phút


@dataclass(frozen=True)
class PendingChallenge:
    code: str
    token: str


@dataclass
class ShopState:
    """Mọi trạng thái đổi theo request; `reset()` đưa về ban đầu (cho test)."""

    captcha_after: int
    clock: Callable[[], float] = time.time
    hits: int = 0
    challenge: PendingChallenge | None = None
    passes: dict[str, float] = field(default_factory=dict)  # cookie -> thời điểm hết hạn

    def __post_init__(self) -> None:
        if self.captcha_after < 1:
            raise ValueError(f"captcha_after must be >= 1, got {self.captcha_after}")

    def reset(self) -> None:
        self.hits = 0
        self.challenge = None
        self.passes.clear()

    def has_valid_pass(self, cookie: str | None) -> bool:
        if not cookie:
            return False
        expires = self.passes.get(cookie)
        if expires is None:
            return False
        if expires <= self.clock():
            del self.passes[cookie]
            return False
        return True

    def requires_challenge(self, cookie: str | None) -> PendingChallenge | None:
        """Tính một request trang nội dung; trả challenge nếu phải chặn.

        Từ request thứ `captcha_after + 1` không có cookie hợp lệ, trang bị chặn tới khi giải đúng.
        """
        if self.has_valid_pass(cookie):
            return None
        self.hits += 1
        if self.challenge is None and self.hits > self.captcha_after:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            self.challenge = PendingChallenge(code=code, token=secrets.token_urlsafe(8))
        return self.challenge

    def solve(self, token: str, answer: str) -> str | None:
        """Cookie `mock_pass` mới nếu `token` và `answer` đúng, ngược lại `None`."""
        challenge = self.challenge
        if challenge is None:
            return None
        token_ok = hmac.compare_digest(token.encode(), challenge.token.encode())
        answer_ok = hmac.compare_digest(answer.strip().upper().encode(), challenge.code.encode())
        if not (token_ok and answer_ok):
            return None
        cookie = secrets.token_urlsafe(16)
        self.passes[cookie] = self.clock() + PASS_TTL_SECONDS
        self.challenge = None
        self.hits = 0
        return cookie
