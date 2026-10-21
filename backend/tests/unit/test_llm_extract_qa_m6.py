"""QA M6: LlmSpecsFiller với đầu vào Unicode, cache hỏng và giá trị rác (không gọi mạng)."""

import unicodedata
from typing import Any

import pytest

from app.agent.testing import ScriptedChatModel
from app.domain.enums import Category
from app.normalize.llm_extract import LlmSpecsFiller, content_hash
from app.normalize.specs import LaptopSpecs
from tests.unit.test_llm_extract import ACER, RAW, MemoryCache, filler, rule_extraction


def test_grounding_works_across_unicode_forms_of_the_source_text() -> None:
    raw = {"Ghi chú": unicodedata.normalize("NFD", "Card rời RTX 4050 6GB")}
    fill, _ = filler(LaptopSpecs(gpu_model="RTX 4050"))

    after = fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction(ACER, raw))

    assert after.specs["gpu_model"] == "RTX 4050"


@pytest.mark.parametrize("blank", ["", "   ", "\t", "-"])
def test_blank_or_symbol_only_values_are_never_grounded(blank: str) -> None:
    fill, _ = filler(LaptopSpecs.model_construct(gpu_model=blank))
    before = rule_extraction()

    after = fill(MemoryCache(), Category.laptop, ACER, RAW, before)

    assert "gpu_model" not in after.specs
    assert after.missing == before.missing and after.confidence == before.confidence


def test_value_only_after_the_input_cap_is_not_grounded() -> None:
    """LLM chỉ thấy 300 ký tự đầu của mỗi giá trị; GPU nằm sau đó thì không thể do nó đọc ra."""
    raw = {"Ghi chú": "x" * 400 + " Card rời RTX 4050"}
    fill, _ = filler(LaptopSpecs(gpu_model="RTX 4050"))
    before = rule_extraction(ACER, raw)
    assert before.missing == ("gpu_model",)

    after = fill(MemoryCache(), Category.laptop, ACER, raw, before)

    assert "gpu_model" not in after.specs


def test_poisoned_cache_entry_keeps_the_valid_field_and_drops_the_invalid_one() -> None:
    cache = MemoryCache()
    cache.entries[content_hash(Category.laptop, ACER, RAW)] = {
        "ram_gb": -5,  # sai miền
        "storage_gb": "nhiều",  # sai kiểu
        "gpu_model": "RTX 4050",
    }
    fill, model = filler()

    after = fill(cache, Category.laptop, ACER, RAW, rule_extraction())

    assert after.specs["gpu_model"] == "RTX 4050" and after.specs["ram_gb"] == 8
    assert model.calls == [] and fill.cache_hits == 1


@pytest.mark.parametrize("garbage", [{}, {"gpu_model": 123}, {"gpu_model": ["a", None]}, {"x": 1}])
def test_garbage_cache_entry_never_raises_and_changes_nothing(garbage: dict[str, Any]) -> None:
    cache = MemoryCache()
    cache.entries[content_hash(Category.laptop, ACER, RAW)] = garbage
    fill, _ = filler()
    before = rule_extraction()

    after = fill(cache, Category.laptop, ACER, RAW, before)

    assert after.specs == before.specs and after.missing == before.missing


def test_fields_the_rules_already_read_are_ignored_even_when_the_llm_disagrees() -> None:
    fill, _ = filler(LaptopSpecs(gpu_model="RTX 4050", ram_gb=64, storage_gb=4000))
    before = rule_extraction()

    after = fill(MemoryCache(), Category.laptop, ACER, RAW, before)

    assert (after.specs["ram_gb"], after.specs["storage_gb"]) == (
        before.specs["ram_gb"],
        before.specs["storage_gb"],
    )


def test_two_fillers_sharing_a_cache_call_the_llm_once_in_total() -> None:
    cache = MemoryCache()
    first, model_a = filler(LaptopSpecs(gpu_model="RTX 4050"))
    second = LlmSpecsFiller(ScriptedChatModel(script=[]), "p", model_name="other")

    first(cache, Category.laptop, ACER, RAW, rule_extraction())
    after = second(cache, Category.laptop, ACER, RAW, rule_extraction())

    assert after.specs["gpu_model"] == "RTX 4050"
    assert (len(model_a.calls), second.llm_calls, second.cache_hits) == (1, 0, 1)
