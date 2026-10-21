"""Lắp bộ LLM dự phòng trích thông số (T5.3) cho nơi chạy thu thập (script, worker).

Trả `None` (không dùng LLM) khi tắt bằng `LLM_EXTRACTOR_ENABLED`, khi `LLM_PROVIDER=fake`, hoặc khi
thiếu khóa API: thu thập vẫn chạy bằng luật, chỉ không điền được trường còn thiếu.
"""

import logging

from app.agent.llm import get_chat_model
from app.agent.prompts import load_prompt
from app.config import Settings
from app.domain.errors import LlmUnavailable
from app.normalize.llm_extract import LlmSpecsFiller

logger = logging.getLogger(__name__)


def build_spec_filler(settings: Settings) -> LlmSpecsFiller | None:
    if not settings.llm_extractor_enabled or settings.llm_provider == "fake":
        return None
    try:
        model = get_chat_model("extractor", settings)
    except LlmUnavailable as error:
        logger.warning("Tắt LLM dự phòng trích thông số: %s", error.message)
        return None
    name = settings.gemini_model if settings.llm_provider == "gemini" else settings.openai_model
    return LlmSpecsFiller(model, load_prompt("extractor"), model_name=name)
