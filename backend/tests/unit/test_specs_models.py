"""Khung thông số theo nhóm (app/normalize/specs, docs/04 §5)."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.domain.enums import Category
from app.normalize.specs import (
    REQUIRED_FIELDS,
    SPEC_MODELS,
    HeadsetSpecs,
    KeyboardSpecs,
    LaptopSpecs,
    MouseSpecs,
    PhoneSpecs,
)

LAPTOP_EXAMPLE: dict[str, Any] = {
    "cpu_model": "i7-13620H",
    "cpu_vendor": "intel",
    "gpu_model": "RTX 4060",
    "gpu_vram_gb": 8,
    "ram_gb": 16,
    "storage_gb": 512,
    "storage_type": "ssd",
    "screen_in": 15.6,
    "resolution": "1920x1080",
    "refresh_hz": 144,
    "panel": "IPS",
    "weight_kg": 2.2,
    "os": "Windows 11 Home",
    "is_gaming": True,
}
MOUSE_EXAMPLE: dict[str, Any] = {
    "connection": ["wired", "wireless_2_4"],
    "dpi_max": 26000,
    "sensor": "HERO 25K",
    "buttons": 6,
    "weight_g": 63,
    "rgb": True,
    "shape": "ambidextrous",
}
KEYBOARD_EXAMPLE: dict[str, Any] = {
    "connection": ["wired"],
    "switch_type": "mechanical",
    "switch_name": "Gateron Brown",
    "form_factor": "tkl",
    "hot_swap": True,
    "backlight": "rgb",
}
HEADSET_EXAMPLE: dict[str, Any] = {
    "form": "over_ear",
    "connection": ["usb"],
    "has_mic": True,
    "anc": False,
    "surround_7_1": True,
    "driver_mm": 50,
}
PHONE_EXAMPLE: dict[str, Any] = {
    "chipset": "Snapdragon 8 Gen 3",
    "ram_gb": 12,
    "storage_gb": 256,
    "screen_in": 6.7,
    "battery_mah": 5000,
    "os": "Android 14",
}
EXAMPLES: dict[Category, dict[str, Any]] = {
    Category.laptop: LAPTOP_EXAMPLE,
    Category.mouse: MOUSE_EXAMPLE,
    Category.keyboard: KEYBOARD_EXAMPLE,
    Category.headset: HEADSET_EXAMPLE,
    Category.phone: PHONE_EXAMPLE,
}


# --- Đăng ký theo nhóm ----------------------------------------------------------------------


def test_spec_models_cover_every_category_except_other() -> None:
    assert set(SPEC_MODELS) == set(Category) - {Category.other}
    assert SPEC_MODELS[Category.laptop] is LaptopSpecs
    assert SPEC_MODELS[Category.mouse] is MouseSpecs
    assert SPEC_MODELS[Category.keyboard] is KeyboardSpecs
    assert SPEC_MODELS[Category.headset] is HeadsetSpecs
    assert SPEC_MODELS[Category.phone] is PhoneSpecs


def test_required_fields_match_documented_columns() -> None:
    assert {
        Category.laptop: ("cpu_model", "gpu_model", "ram_gb", "storage_gb"),
        Category.mouse: ("connection",),
        Category.keyboard: ("connection", "switch_type"),
        Category.headset: ("form", "connection"),
        Category.phone: ("ram_gb", "storage_gb"),
    } == REQUIRED_FIELDS


def test_registries_are_read_only() -> None:
    with pytest.raises(TypeError):
        SPEC_MODELS[Category.other] = LaptopSpecs  # type: ignore[index]
    with pytest.raises(TypeError):
        REQUIRED_FIELDS[Category.laptop] = ()  # type: ignore[index]


@pytest.mark.parametrize("category", list(SPEC_MODELS))
def test_required_fields_are_fields_of_the_model(category: Category) -> None:
    model = SPEC_MODELS[category]
    assert set(REQUIRED_FIELDS[category]) <= set(model.model_fields)


@pytest.mark.parametrize("category", list(SPEC_MODELS))
def test_every_field_is_optional_when_parsing(category: Category) -> None:
    empty = SPEC_MODELS[category].model_validate({})
    assert all(value is None for value in empty.model_dump().values())


# --- Ví dụ trong docs parse được và round-trip qua JSON -------------------------------------


@pytest.mark.parametrize("category", list(SPEC_MODELS))
def test_documented_example_round_trips_through_json_dump(category: Category) -> None:
    model = SPEC_MODELS[category]
    parsed = model.model_validate(EXAMPLES[category])
    dumped = parsed.model_dump(mode="json")
    assert model.model_validate(dumped) == parsed
    assert all(value is not None for value in dumped.values())


def test_json_dump_uses_plain_strings_for_enums() -> None:
    dumped = KeyboardSpecs.model_validate(KEYBOARD_EXAMPLE).model_dump(mode="json")
    assert dumped["connection"] == ["wired"]
    assert dumped["switch_type"] == "mechanical"
    assert dumped["form_factor"] == "tkl"
    assert dumped["backlight"] == "rgb"


@pytest.mark.parametrize("value", ["full", "tkl", "75", "65", "60", "other"])
def test_keyboard_form_factor_accepts_documented_values(value: str) -> None:
    spec = KeyboardSpecs.model_validate({"form_factor": value})
    assert spec.model_dump(mode="json")["form_factor"] == value


def test_mouse_connection_accepts_several_values_in_order() -> None:
    spec = MouseSpecs.model_validate({"connection": ["bluetooth", "wired", "wireless_2_4"]})
    assert spec.model_dump(mode="json")["connection"] == ["bluetooth", "wired", "wireless_2_4"]


def test_headset_connection_uses_headset_values() -> None:
    assert HeadsetSpecs.model_validate({"connection": ["wired_3_5", "usb"]}).connection is not None
    with pytest.raises(ValidationError):
        MouseSpecs.model_validate({"connection": ["usb"]})  # `usb` chỉ hợp lệ với tai nghe


# --- Từ chối dữ liệu sai --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (LaptopSpecs, {"cpu_vendor": "via"}),
        (LaptopSpecs, {"storage_type": "nvme"}),
        (MouseSpecs, {"shape": "left"}),
        (MouseSpecs, {"connection": ["infrared"]}),
        (KeyboardSpecs, {"switch_type": "topre"}),
        (KeyboardSpecs, {"form_factor": "80"}),
        (KeyboardSpecs, {"backlight": "blue"}),
        (HeadsetSpecs, {"form": "neckband"}),
        (HeadsetSpecs, {"connection": ["wired"]}),
    ],
)
def test_unknown_enum_value_is_rejected(model: type[BaseModel], data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (LaptopSpecs, "ram_gb"),
        (LaptopSpecs, "storage_gb"),
        (LaptopSpecs, "refresh_hz"),
        (MouseSpecs, "dpi_max"),
        (MouseSpecs, "buttons"),
        (MouseSpecs, "weight_g"),
        (HeadsetSpecs, "driver_mm"),
        (PhoneSpecs, "ram_gb"),
        (PhoneSpecs, "storage_gb"),
        (PhoneSpecs, "battery_mah"),
    ],
)
@pytest.mark.parametrize("bad", [True, "16", 16.0, -1, 0])
def test_integer_fields_are_strict_and_positive(
    model: type[BaseModel], field: str, bad: Any
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({field: bad})


@pytest.mark.parametrize("bad", [True, "16", 16.0, -1])
def test_vram_is_strict_integer_but_zero_is_valid_for_integrated_gpu(bad: Any) -> None:
    assert LaptopSpecs.model_validate({"gpu_vram_gb": 0}).gpu_vram_gb == 0
    with pytest.raises(ValidationError):
        LaptopSpecs.model_validate({"gpu_vram_gb": bad})


@pytest.mark.parametrize("bad", [True, "2.2", "15.6"])
def test_float_fields_are_strict(bad: Any) -> None:
    for model, field in (
        (LaptopSpecs, "weight_kg"),
        (LaptopSpecs, "screen_in"),
        (PhoneSpecs, "screen_in"),
    ):
        with pytest.raises(ValidationError):
            model.model_validate({field: bad})


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (LaptopSpecs, "screen_in"),
        (LaptopSpecs, "weight_kg"),
        (PhoneSpecs, "screen_in"),
    ],
)
@pytest.mark.parametrize("bad", [0, -1.5, float("nan"), float("inf")])
def test_float_fields_must_be_finite_and_positive(
    model: type[BaseModel], field: str, bad: float
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({field: bad})


def test_float_fields_accept_integers_and_decimals() -> None:
    assert LaptopSpecs.model_validate({"screen_in": 14}).screen_in == 14.0
    assert LaptopSpecs.model_validate({"weight_kg": 1.35}).weight_kg == 1.35


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (LaptopSpecs, "cpu_model"),
        (LaptopSpecs, "gpu_model"),
        (MouseSpecs, "sensor"),
        (KeyboardSpecs, "switch_name"),
        (PhoneSpecs, "chipset"),
    ],
)
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_text_is_rejected(model: type[BaseModel], field: str, blank: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({field: blank})


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (LaptopSpecs, "is_gaming"),
        (MouseSpecs, "rgb"),
        (KeyboardSpecs, "hot_swap"),
        (HeadsetSpecs, "anc"),
    ],
)
def test_bool_fields_do_not_accept_arbitrary_text(model: type[BaseModel], field: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({field: "maybe"})


def test_text_fields_are_stripped() -> None:
    assert LaptopSpecs.model_validate({"cpu_model": "  i5-12450H "}).cpu_model == "i5-12450H"


def test_unknown_keys_are_ignored() -> None:
    spec = MouseSpecs.model_validate({"dpi_max": 8000, "colour": "black"})
    assert spec.dpi_max == 8000
    assert "colour" not in spec.model_dump()


# --- LaptopSpecs: gpu_model chuẩn hóa, gpu_rank dẫn xuất ------------------------------------


def test_laptop_gpu_model_is_normalized_and_rank_is_derived() -> None:
    spec = LaptopSpecs.model_validate({"gpu_model": "GeForce RTX4060 8GB"})
    assert spec.gpu_model == "RTX 4060"
    assert spec.gpu_rank == 40


def test_laptop_gpu_rank_passed_in_is_ignored() -> None:
    spec = LaptopSpecs.model_validate({"gpu_model": "RTX 4060", "gpu_rank": 99})
    assert spec.gpu_rank == 40
    # Cả giá trị rác cũng không làm lỗi vì đầu vào này bị bỏ qua.
    assert LaptopSpecs.model_validate({"gpu_model": "RTX 4060", "gpu_rank": "abc"}).gpu_rank == 40


def test_laptop_gpu_rank_follows_gpu_model_when_reassigned() -> None:
    spec = LaptopSpecs(gpu_model="RTX 4060")
    spec.gpu_model = "RTX 5090"
    assert spec.gpu_rank == 85
    spec.gpu_model = None
    assert spec.gpu_rank is None


def test_laptop_gpu_rank_is_read_only() -> None:
    spec = LaptopSpecs(gpu_model="RTX 4060")
    with pytest.raises(AttributeError):
        spec.gpu_rank = 1  # type: ignore[misc]


def test_laptop_gpu_model_with_two_different_gpus_is_kept_raw_with_null_rank() -> None:
    spec = LaptopSpecs.model_validate({"gpu_model": "RTX 4050 6GB (up to RTX 4060)"})
    assert spec.gpu_model == "RTX 4050 6GB (up to RTX 4060)"
    assert spec.gpu_rank is None


def test_laptop_gpu_rank_without_gpu_model_is_cleared() -> None:
    assert LaptopSpecs.model_validate({"gpu_rank": 40}).gpu_rank is None


def test_laptop_integrated_gpu_has_rank_zero() -> None:
    spec = LaptopSpecs.model_validate({"gpu_model": "Intel Iris Xe Graphics"})
    assert spec.gpu_model == "Integrated"
    assert spec.gpu_rank == 0


@pytest.mark.parametrize(
    ("raw", "model"),
    [
        ("RTX 4070 Ti", "RTX 4070 Ti"),  # nhận ra nhưng chưa có trong bảng hạng
        ("GTX 1650", "GTX 1650"),
        ("Mystery GPU 9000", "Mystery GPU 9000"),  # không nhận ra: giữ nguyên chuỗi
    ],
)
def test_laptop_gpu_not_in_rank_table_keeps_name_with_null_rank(raw: str, model: str) -> None:
    spec = LaptopSpecs.model_validate({"gpu_model": raw})
    assert spec.gpu_model == model
    assert spec.gpu_rank is None


def test_laptop_json_dump_contains_derived_rank_for_jsonb_filtering() -> None:
    dumped = LaptopSpecs.model_validate(LAPTOP_EXAMPLE).model_dump(mode="json")
    assert dumped["gpu_rank"] == 40
    assert dumped["is_gaming"] is True
    assert dumped["gpu_model"] == "RTX 4060"


def test_laptop_round_trip_keeps_rank_after_revalidation() -> None:
    first = LaptopSpecs.model_validate({"gpu_model": "rtx3050ti"})
    again = LaptopSpecs.model_validate(first.model_dump(mode="json"))
    assert again.gpu_model == "RTX 3050 Ti"
    assert again.gpu_rank == 22
    assert again == first
