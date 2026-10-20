"""LLM dự phòng cho bộ trích xuất theo luật (T5.3, docs/04 §7).

Chỉ chạy khi luật còn thiếu trường bắt buộc. Kết quả đi qua khung thông số của nhóm, chỉ điền
những trường đang thiếu (không ghi đè giá trị luật đã đọc) và được cache theo hash nên cùng một
đầu vào không gọi LLM lần hai. Lỗi LLM không làm hỏng mục: giữ kết quả theo luật.

Module này không biết CSDL hay `app.agent`: cache và prompt được tiêm từ nơi lắp ráp.
"""

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.domain.enums import Category
from app.normalize.extract import (
    SpecsExtraction,
    merge_specs,
    missing_required,
    specs_confidence,
)
from app.normalize.specs import SPEC_MODELS

logger = logging.getLogger(__name__)


class SpecsCache(Protocol):
    """Cache kết quả LLM theo hash nội dung."""

    def get(self, content_hash: str) -> Mapping[str, Any] | None: ...

    def put(
        self, content_hash: str, category: Category, result: Mapping[str, Any], model: str
    ) -> None: ...


def content_hash(category: Category, title: str, raw_specs: Mapping[str, str]) -> str:
    """SHA-256 của (nhóm, tiêu đề, bảng thông số thô); không phụ thuộc thứ tự nhãn."""
    payload = json.dumps(
        [category.value, title, sorted(raw_specs.items())], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LlmSpecsFiller:
    """Điền trường bắt buộc còn thiếu bằng LLM. Gọi đồng bộ (pipeline chạy trong luồng riêng)."""

    def __init__(
        self,
        model: BaseChatModel,
        system_prompt: str,
        *,
        model_name: str = "unknown",
        enabled: bool = True,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt
        self._model_name = model_name
        self.enabled = enabled
        self.llm_calls = 0
        self.cache_hits = 0

    def __call__(
        self,
        cache: SpecsCache,
        category: Category,
        title: str,
        raw_specs: Mapping[str, str],
        extraction: SpecsExtraction,
    ) -> SpecsExtraction:
        schema = SPEC_MODELS.get(category)
        if not self.enabled or not extraction.missing or schema is None:
            return extraction
        key = content_hash(category, title, raw_specs)
        found = cache.get(key)
        if found is not None:
            self.cache_hits += 1
            llm_specs: Mapping[str, Any] = found
            logger.info("LLM extractor: cache hit %s (tổng %d)", key[:12], self.cache_hits)
        else:
            llm_specs_or_none = self._call_llm(schema, title, raw_specs)
            if llm_specs_or_none is None:
                return extraction
            llm_specs = llm_specs_or_none
            cache.put(key, category, llm_specs, self._model_name)
        wanted = {name: value for name, value in llm_specs.items() if name in extraction.missing}
        specs = merge_specs(category, extraction.specs, wanted)
        return SpecsExtraction(
            specs=specs,
            missing=missing_required(category, specs),
            confidence=specs_confidence(category, specs),
        )

    def _call_llm(
        self, schema: type[BaseModel], title: str, raw_specs: Mapping[str, str]
    ) -> dict[str, Any] | None:
        self.llm_calls += 1
        logger.info("LLM extractor: gọi LLM lần %d cho %r", self.llm_calls, title[:80])
        data = json.dumps({"title": title, "specs": dict(raw_specs)}, ensure_ascii=False)
        try:
            result = self._model.with_structured_output(schema).invoke(
                [SystemMessage(content=self._system_prompt), HumanMessage(content=data)]
            )
            if not isinstance(result, schema):
                result = schema.model_validate(result)
            return result.model_dump(mode="json", exclude_none=True)
        except Exception:
            logger.warning(
                "LLM extractor lỗi, giữ kết quả theo luật cho %r", title[:80], exc_info=True
            )
            return None
