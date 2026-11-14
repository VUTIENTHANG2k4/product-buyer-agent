"""Thử lại lời gọi LLM khi lỗi tạm thời (X4, docs/05 §2).

Gemini gói miễn phí hay trả 503 "high demand" (eval 2026-11-13: 10/34 câu hỏng trong một lượt).
Thử lại ở tầng agent, không dùng cơ chế của SDK, để mỗi lần thử đi qua bộ giới hạn `LLM_MAX_RPM`
của LangChain và có log kèm `[run <id>]`; thử lại của SDK bị tắt ở `llm.py`.

Phân loại (xét cả chuỗi `__cause__`/`__context__`): lỗi chuẩn của LangChain (`ModelError`, mà
langchain-google-genai và langchain-openai đều bọc lỗi SDK thành) quyết định bằng `is_retryable`
(quá tải/5xx, 429, hết thời gian, lỗi kết nối); không có thì xét mã HTTP 408/429/500/502/503/504
(`code`/`status_code`) rồi `TimeoutError` và lỗi mạng của httpx. Lỗi nghiệp vụ của ứng dụng
(`AppError`, ví dụ `LlmUnavailable` có status 503), lỗi dữ liệu (JSON sai, sai khung), 400, 401,
403, 404 không thử lại.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, TypeVar

import httpx
from langchain_core.exceptions import ModelError

from app.config import Settings
from app.domain.errors import AppError

logger = logging.getLogger(__name__)

T = TypeVar("T")

TRANSIENT_STATUS: Final = frozenset({408, 429, 500, 502, 503, 504})
_MAX_CHAIN: Final = 10  # số tầng `__cause__`/`__context__` tối đa khi tìm mã lỗi
# Lỗi mạng tạm thời của httpx (Gemini async dùng httpx.AsyncClient); `UnsupportedProtocol`,
# `LocalProtocolError` là lỗi cấu hình/lập trình nên không thử lại (review X4).
_NETWORK_ERRORS: Final = (
    TimeoutError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


@dataclass(frozen=True)
class RetryPolicy:
    """Số lần gọi tối đa (kể cả lần đầu) và cách giãn cách giữa các lần (giây).

    Lần chờ thứ k = `min(max_delay_s, base_delay_s · 2^(k-1))` nhân hệ số ngẫu nhiên trong
    [0,5; 1]; tổng thời gian chờ không vượt `max_total_wait_s` (hết ngân sách thì thôi thử).
    """

    attempts: int = 1
    base_delay_s: float = 2.0
    max_delay_s: float = 10.0
    max_total_wait_s: float = 20.0
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, compare=False)
    random: Callable[[], float] = field(default=random.random, compare=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetryPolicy":
        return cls(
            attempts=settings.llm_retry_attempts,
            base_delay_s=settings.llm_retry_base_seconds,
            max_delay_s=settings.llm_retry_max_delay_seconds,
            max_total_wait_s=settings.llm_retry_max_total_seconds,
        )

    def delay(self, retry: int) -> float:
        """Thời gian chờ (giây) trước lần thử lại thứ `retry` (bắt đầu từ 1)."""
        raw = min(self.max_delay_s, self.base_delay_s * 2.0 ** (retry - 1))
        return raw * (0.5 + 0.5 * self.random())


NO_RETRY: Final = RetryPolicy(attempts=1)


def _chain(error: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in seen and len(seen) < _MAX_CHAIN:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def status_of(error: BaseException) -> int | None:
    """Mã HTTP đầu tiên tìm thấy trên lỗi hoặc nguyên nhân của nó (None nếu không có).

    Bỏ qua `AppError`: `status_code` của nó là mã trả cho client của API này, không phải mã của
    nhà cung cấp LLM (`LlmUnavailable` là 503 nhưng thử lại không giúp gì).
    """
    for item in _chain(error):
        if isinstance(item, AppError):
            continue
        for name in ("code", "status_code"):
            value = getattr(item, name, None)
            if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
                return value
    return None


def is_transient(error: BaseException) -> bool:
    """Lỗi có thể hết khi thử lại sau ít giây (quá tải, giới hạn tần suất, mạng)."""
    chain = _chain(error)
    if any(isinstance(item, AppError) for item in chain):
        return False
    model_error = next((item for item in chain if isinstance(item, ModelError)), None)
    if model_error is not None:
        return bool(model_error.is_retryable)
    status = status_of(error)
    if status is not None:
        return status in TRANSIENT_STATUS
    return any(isinstance(item, _NETWORK_ERRORS) for item in chain)


async def call_with_retry(
    call: Callable[[], Awaitable[T]], policy: RetryPolicy, *, tag: str = "", stage: str = "llm"
) -> T:
    """Chạy `call`, thử lại khi lỗi tạm thời theo `policy`; hết lần thì ném lại lỗi cuối."""
    waited = 0.0
    attempt = 1
    while True:
        try:
            return await call()
        except Exception as error:
            if attempt >= policy.attempts or not is_transient(error):
                raise
            pause = policy.delay(attempt)
            if waited + pause > policy.max_total_wait_s:
                raise
            status = status_of(error)
            logger.warning(
                "%sLLM %s lỗi tạm thời %s%s, thử lại lần %d sau %.1f s",
                tag,
                stage,
                type(error).__name__,
                f"/{status}" if status is not None else "",
                attempt,
                pause,
            )
            await policy.sleep(pause)
            waited += pause
            attempt += 1
