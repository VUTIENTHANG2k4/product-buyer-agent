"""Nhà máy model chat theo vai trò (docs/05 §2).

Nhà cung cấp chọn bằng `LLM_PROVIDER`: `gemini`, `openai` hoặc `fake` (test/e2e). Mỗi lần gọi LLM
hết hạn sau 30 giây và thử lại 1 lần.
"""

from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.agent.testing import ScriptedChatModel
from app.config import Settings, get_settings
from app.domain.errors import LlmUnavailable

Role = Literal["planner", "executor", "extractor"]

LLM_TIMEOUT_SECONDS = 30.0
LLM_MAX_RETRIES = 1
# Planner và extractor cần kết quả ổn định; executor được lệch nhẹ khi viết câu trả lời.
TEMPERATURE: dict[Role, float] = {"planner": 0.0, "executor": 0.2, "extractor": 0.0}


@lru_cache
def _rate_limiter(requests_per_minute: int) -> InMemoryRateLimiter:
    """Một bộ giới hạn dùng chung cho mọi model cùng cấu hình (hạn mức tính theo dự án/model)."""
    return InMemoryRateLimiter(
        requests_per_second=requests_per_minute / 60, check_every_n_seconds=0.1, max_bucket_size=1
    )


def _limiter(settings: Settings) -> InMemoryRateLimiter | None:
    return _rate_limiter(settings.llm_max_rpm) if settings.llm_max_rpm > 0 else None


def get_chat_model(role: Role, settings: Settings | None = None) -> BaseChatModel:
    """Model chat cho `role`. Thiếu khóa API của nhà cung cấp được chọn → `LlmUnavailable`."""
    settings = settings or get_settings()
    temperature = TEMPERATURE[role]
    provider = settings.llm_provider
    if provider == "fake":
        return ScriptedChatModel()
    if provider == "gemini":
        google_key = settings.google_api_key
        if not google_key.get_secret_value():
            raise LlmUnavailable("Thiếu GOOGLE_API_KEY cho LLM_PROVIDER=gemini")
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            temperature=temperature,
            api_key=google_key,
            request_timeout=LLM_TIMEOUT_SECONDS,
            retries=LLM_MAX_RETRIES,
            rate_limiter=_limiter(settings),
        )
    openai_key = settings.openai_api_key
    if not openai_key.get_secret_value():
        raise LlmUnavailable("Thiếu OPENAI_API_KEY cho LLM_PROVIDER=openai")
    return ChatOpenAI(
        model=settings.openai_model,
        temperature=temperature,
        api_key=openai_key,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
        rate_limiter=_limiter(settings),
    )
