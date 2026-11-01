"""QA small-fixes-6: `llm_extract` với `raw_specs` có nhãn/giá trị không phải chuỗi (T5.10).

JSON cũ trong CSDL có thể chứa số, bool, `null`, danh sách, dict. Các cặp đó phải bị bỏ qua ở cả
ba nơi: văn bản kiểm chứng, dữ liệu gửi LLM và hash cache.
"""

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from app.domain.enums import Category
from app.normalize.llm_extract import MAX_SPEC_ENTRIES, content_hash
from app.normalize.specs import LaptopSpecs
from tests.unit.test_llm_extract import ACER, RAW, MemoryCache, filler, rule_extraction

JUNK: list[Any] = [
    True,
    False,
    0,
    1.5,
    float("nan"),
    None,
    ["RTX 4050"],
    ("RTX 4050",),
    {"gpu": "RTX 4050"},
    b"RTX 4050",
    bytearray(b"RTX 4050"),
    Decimal("1.5"),
    {1, 2},
    object,
]


JUNK_ONLY: dict[str, Any] = {"a": 1, "b": None}


def payload_specs(model: Any) -> dict[str, str]:
    data = json.loads(str(model.calls[0][1].content))
    specs = data["specs"]
    assert isinstance(specs, dict)
    return specs


# ---------------------------------------------------------------- 1. giá trị không phải chuỗi
@pytest.mark.parametrize("junk", JUNK, ids=lambda value: type(value).__name__ + repr(value)[:12])
def test_a_value_of_any_non_string_type_is_dropped_from_the_llm_payload(junk: Any) -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))

    after = fill(MemoryCache(), Category.laptop, ACER, {**RAW, "Nhãn rác": junk}, rule_extraction())

    assert after.specs["gpu_model"] == "RTX 4050"
    assert payload_specs(model) == RAW


@pytest.mark.parametrize("junk", JUNK, ids=lambda value: type(value).__name__ + repr(value)[:12])
def test_a_value_of_any_non_string_type_does_not_change_the_cache_key(junk: Any) -> None:
    clean = content_hash(Category.laptop, ACER, RAW)

    assert content_hash(Category.laptop, ACER, {**RAW, "Nhãn rác": junk}) == clean


@pytest.mark.parametrize("junk", [True, 5, None, ["RTX 4090"], {"gpu": "RTX 4090"}, b"RTX 4090"])
def test_a_gpu_that_appears_only_in_a_non_string_value_is_not_grounded(junk: Any) -> None:
    fill, _ = filler(LaptopSpecs(gpu_model="RTX 4090"))
    raw = {**RAW, "GPU": junk}

    after = fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction(ACER, raw))

    assert "gpu_model" not in after.specs


def test_the_second_run_hits_the_cache_when_only_the_junk_entries_differ() -> None:
    cache = MemoryCache()
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))

    first = fill(cache, Category.laptop, ACER, {**RAW, "Số nút": 6}, rule_extraction())
    second = fill(
        cache, Category.laptop, ACER, {**RAW, "Số nút": 7, "Khác": None}, rule_extraction()
    )

    assert first.specs["gpu_model"] == second.specs["gpu_model"] == "RTX 4050"
    assert len(model.calls) == 1 and fill.cache_hits == 1


# ---------------------------------------------------------------- 2. nhãn không phải chuỗi
@pytest.mark.parametrize("label", [1, 2.5, None, (1, 2), b"label", True])
def test_a_label_that_is_not_a_string_is_dropped_everywhere(label: Any) -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))
    raw: dict[Any, Any] = {**RAW, label: "RTX 4090 6GB"}

    after = fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction())

    assert after.specs["gpu_model"] == "RTX 4050"
    assert payload_specs(model) == RAW
    assert content_hash(Category.laptop, ACER, raw) == content_hash(Category.laptop, ACER, RAW)


def test_a_value_only_present_under_a_non_string_label_is_not_a_grounding_source() -> None:
    fill, _ = filler(LaptopSpecs(gpu_model="RTX 4090"))
    raw: dict[Any, Any] = {**RAW, 7: "Card rời RTX 4090"}

    after = fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction())

    assert "gpu_model" not in after.specs


# ---------------------------------------------------------------- 3. rỗng, chỉ rác, kiểu Mapping
def test_empty_and_all_junk_tables_send_an_empty_specs_object_and_share_one_cache_key() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))

    fill(MemoryCache(), Category.laptop, ACER, JUNK_ONLY, rule_extraction(ACER, {}))

    assert payload_specs(model) == {}
    assert content_hash(Category.laptop, ACER, JUNK_ONLY) == content_hash(Category.laptop, ACER, {})


def test_a_read_only_mapping_is_accepted() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))
    raw = MappingProxyType({**RAW, "Số nút": 6})

    after = fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction())

    assert after.specs["gpu_model"] == "RTX 4050"
    assert payload_specs(model) == RAW


# ---------------------------------------------------------------- 4. hash
def test_hash_is_the_same_whatever_the_order_of_the_labels() -> None:
    forward = {"a": "1", "b": "2", "c": "3"}
    backward = dict(reversed(list(forward.items())))

    assert content_hash(Category.laptop, "t", forward) == content_hash(
        Category.laptop, "t", backward
    )


def test_hash_of_string_only_tables_is_unchanged_by_the_filter_so_old_cache_rows_stay_valid() -> (
    None
):
    raw = {"Ghi chú": "Card rời RTX 4050", "CPU": "Core 5", "Ghi chú 2": "Tiếng Việt: đ"}
    old_payload = json.dumps(
        ["laptop", "Tiêu đề", sorted(raw.items())], ensure_ascii=False, sort_keys=True
    )

    assert (
        content_hash(Category.laptop, "Tiêu đề", raw)
        == hashlib.sha256(old_payload.encode("utf-8")).hexdigest()
    )


def test_hash_changes_with_category_title_label_and_value() -> None:
    base = content_hash(Category.laptop, "t", {"a": "1"})

    variants = {
        content_hash(Category.mouse, "t", {"a": "1"}),
        content_hash(Category.laptop, "u", {"a": "1"}),
        content_hash(Category.laptop, "t", {"b": "1"}),
        content_hash(Category.laptop, "t", {"a": "2"}),
        content_hash(Category.laptop, "t", {"a": "1", "b": ""}),
    }

    assert base not in variants and len(variants) == 5


def test_hash_does_not_confuse_a_swapped_label_and_value() -> None:
    assert content_hash(Category.laptop, "t", {"a": "b"}) != content_hash(
        Category.laptop, "t", {"b": "a"}
    )


# ---------------------------------------------------------------- 5. trần số mục sau khi lọc
def test_the_entry_cap_counts_only_string_entries_not_the_junk_in_front() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))
    junk: dict[str, Any] = {f"rác {index}": index for index in range(MAX_SPEC_ENTRIES + 10)}
    text = {f"nhãn {index:03d}": f"giá trị {index}" for index in range(MAX_SPEC_ENTRIES + 10)}
    raw = {**junk, **text}

    fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction(ACER, {}))

    sent = payload_specs(model)
    assert list(sent) == list(text)[:MAX_SPEC_ENTRIES]


def test_junk_interleaved_with_text_does_not_use_up_the_entry_cap() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))
    raw: dict[str, Any] = {}
    for index in range(MAX_SPEC_ENTRIES):
        raw[f"rác {index}"] = index
        raw[f"nhãn {index:03d}"] = f"giá trị {index}"

    fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction(ACER, {}))

    assert len(payload_specs(model)) == MAX_SPEC_ENTRIES


def test_exactly_the_entry_cap_of_string_entries_is_sent_whole() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))
    raw = {f"nhãn {index:03d}": "x" for index in range(MAX_SPEC_ENTRIES)}

    fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction(ACER, {}))

    assert payload_specs(model) == raw


# ---------------------------------------------------------------- 6. cắt độ dài
def test_labels_and_values_are_cut_to_the_cap_and_junk_next_to_them_is_still_ignored() -> None:
    fill, model = filler(LaptopSpecs(gpu_model="RTX 4050"))
    raw: Mapping[str, Any] = {"n" * 500: "v" * 500, "bỏ": 3}

    fill(MemoryCache(), Category.laptop, ACER, raw, rule_extraction(ACER, {}))

    assert payload_specs(model) == {"n" * 300: "v" * 300}
