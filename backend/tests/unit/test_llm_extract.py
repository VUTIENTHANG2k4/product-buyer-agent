"""T5.3: LLM dự phòng trích thông số (model giả, cache trong bộ nhớ)."""

import json
from collections.abc import Mapping
from typing import Any

import pytest

from app.agent.testing import ScriptedChatModel
from app.domain.enums import Category
from app.normalize.extract import SpecsExtraction, extract_specs
from app.normalize.llm_extract import LlmSpecsFiller, content_hash
from app.normalize.specs import LaptopSpecs

ACER = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'
PROMPT = "prompt thử"


class MemoryCache:
    def __init__(self) -> None:
        self.entries: dict[str, Mapping[str, Any]] = {}
        self.models: list[str] = []

    def get(self, content_hash: str) -> Mapping[str, Any] | None:
        return self.entries.get(content_hash)

    def put(
        self, content_hash: str, category: Category, result: Mapping[str, Any], model: str
    ) -> None:
        self.entries[content_hash] = dict(result)
        self.models.append(model)


def rule_extraction(title: str = ACER) -> SpecsExtraction:
    return extract_specs(Category.laptop, title, {})


def filler(*script: Any, enabled: bool = True) -> tuple[LlmSpecsFiller, ScriptedChatModel]:
    model = ScriptedChatModel(script=list(script))
    return LlmSpecsFiller(model, PROMPT, model_name="fake-1", enabled=enabled), model


def test_rules_leave_gpu_missing_for_the_fixture_title() -> None:
    assert rule_extraction().missing == ("gpu_model",)


def test_fills_only_the_missing_field_and_never_overrides_rule_values() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050", ram_gb=16))
    before = rule_extraction()

    after = fill(MemoryCache(), Category.laptop, ACER, {}, before)

    assert after.specs["gpu_model"] == "RTX 4050"
    assert after.specs["gpu_rank"] == 30  # tính lại từ gpu_model sau khi gộp
    assert after.specs["ram_gb"] == before.specs["ram_gb"] == 8
    assert (after.missing, after.confidence) == ((), 1.0)
    assert len(model.calls) == 1


def test_prompt_and_data_are_sent_with_title_and_raw_specs() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))

    fill(MemoryCache(), Category.laptop, ACER, {"Card": "?"}, rule_extraction())

    system, human = model.calls[0]
    assert system.content == PROMPT
    assert json.loads(str(human.content)) == {"title": ACER, "specs": {"Card": "?"}}


def test_not_called_when_nothing_is_missing() -> None:
    fill, model = filler()
    complete = extract_specs(
        Category.mouse, "Chuột Logitech G304 Wireless", {"Kết nối": "Không dây 2.4GHz"}
    )
    assert complete.missing == ()

    assert fill(MemoryCache(), Category.mouse, "x", {}, complete) is complete
    assert model.calls == []


def test_not_called_when_disabled() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"), enabled=False)
    before = rule_extraction()

    assert fill(MemoryCache(), Category.laptop, ACER, {}, before) is before
    assert model.calls == []


def test_second_identical_call_hits_the_cache_and_skips_the_llm() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))
    cache = MemoryCache()

    first = fill(cache, Category.laptop, ACER, {}, rule_extraction())
    second = fill(cache, Category.laptop, ACER, {}, rule_extraction())

    assert second == first
    assert (fill.llm_calls, fill.cache_hits, len(model.calls)) == (1, 1, 1)
    assert cache.models == ["fake-1"]
    assert list(cache.entries) == [content_hash(Category.laptop, ACER, {})]


@pytest.mark.parametrize(
    "bad_reply",
    [
        {"gpu_model": "RTX 4050", "ram_gb": "nhiều"},  # sai kiểu → ValidationError
        RuntimeError("LLM hỏng"),
        TimeoutError("quá hạn"),
    ],
)
def test_llm_failure_keeps_rule_result_and_is_not_cached(bad_reply: object) -> None:
    fill, _ = filler(bad_reply)
    before = rule_extraction()
    cache = MemoryCache()

    assert fill(cache, Category.laptop, ACER, {}, before) is before
    assert cache.entries == {}


def test_script_exhausted_is_treated_as_llm_failure() -> None:
    fill, _ = filler()
    before = rule_extraction()
    assert fill(MemoryCache(), Category.laptop, ACER, {}, before) is before


def test_llm_that_finds_nothing_leaves_missing_and_caches_the_empty_answer() -> None:
    fill, model = filler(LaptopSpecs())
    cache = MemoryCache()

    after = fill(cache, Category.laptop, ACER, {}, rule_extraction())

    assert after.missing == ("gpu_model",)
    assert after.confidence < 0.5
    assert len(cache.entries) == 1
    fill(cache, Category.laptop, ACER, {}, rule_extraction())
    assert len(model.calls) == 1  # lần hai dùng cache, không hỏi lại


def test_content_hash_ignores_label_order_and_separates_category_and_title() -> None:
    base = content_hash(Category.laptop, "a", {"x": "1", "y": "2"})
    assert base == content_hash(Category.laptop, "a", {"y": "2", "x": "1"})
    assert base != content_hash(Category.mouse, "a", {"x": "1", "y": "2"})
    assert base != content_hash(Category.laptop, "b", {"x": "1", "y": "2"})
    assert len(base) == 64


def test_category_without_spec_model_is_skipped() -> None:
    fill, model = filler()
    nothing = SpecsExtraction(specs={}, missing=("x",), confidence=0.0)
    assert fill(MemoryCache(), Category.other, "x", {}, nothing) is nothing
    assert model.calls == []
