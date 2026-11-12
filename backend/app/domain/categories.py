"""Khác biệt theo nhóm hàng tầng 1, đăng ký một lần (X1.11, docs/03 §4).

Thêm một nhóm hàng: thêm giá trị `Category` (kèm migration cho `CHECK`), khung thông số và bộ trích
xuất ở `normalize/specs` (`SPEC_MODELS`, `_EXTRACTORS`), rồi đăng ký một `CategoryProfile` ở đây.
Agent (ý định, câu hỏi lại, bước kế hoạch, LLM giả, `search_catalog`), dịch vụ (thông số nổi bật,
rematch) và quy tắc tên đọc profile thay vì rẽ nhánh theo từng nhóm.

Hàm ở dưới đọc `CATEGORY_PROFILES` lúc gọi (không chép sẵn vào hằng) để test thay registry được.
"""

from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Category

MAX_KEY_SPECS: Final = 6

NameStyle = Literal["model_code", "capacity_variants", "plain"]


class CategoryProfile(BaseModel):
    """Một nhóm hàng tầng 1: tên hiển thị, nguồn bán, thông số nổi bật, quy tắc tên."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: Category
    label_vi: str = Field(min_length=1)  # "điện thoại": bước kế hoạch, câu hỏi lại
    label_en: str = Field(min_length=1)  # "phones": mô tả tool cho LLM
    # Từ nhận diện nhóm của LLM giả (đã `fold`: không dấu, chữ thường).
    detect_words: tuple[str, ...] = Field(min_length=1)
    sources_vi: str = Field(min_length=1)  # trang thật có dữ liệu (docs/02 §2)
    key_spec_fields: tuple[str, ...] = Field(min_length=1, max_length=MAX_KEY_SPECS)
    # Tên chuẩn (`normalize/names.py`): "model_code" = từ hãng đến hết mã model (laptop),
    # "capacity_variants" = bỏ màu/mã phụ sau dung lượng, giữ chuẩn mạng (điện thoại).
    name_style: NameStyle = "plain"
    # Có ghép theo mã model (MPN/mã trong tên) không; phụ kiện không có mã ổn định (docs/04 §7).
    uses_model_code: bool = False


_LAPTOP_AND_ACCESSORY_SOURCES: Final = "GearVN, FPT Shop, An Phát"

CATEGORY_PROFILES: MappingProxyType[Category, CategoryProfile] = MappingProxyType(
    {
        profile.category: profile
        for profile in (
            CategoryProfile(
                category=Category.laptop,
                label_vi="laptop",
                label_en="laptops",
                detect_words=("laptop", "macbook", "may tinh xach tay"),
                sources_vi=_LAPTOP_AND_ACCESSORY_SOURCES,
                key_spec_fields=(
                    "cpu_model",
                    "gpu_model",
                    "ram_gb",
                    "storage_gb",
                    "screen_in",
                    "refresh_hz",
                ),
                name_style="model_code",
                uses_model_code=True,
            ),
            CategoryProfile(
                category=Category.mouse,
                label_vi="chuột",
                label_en="mice",
                detect_words=("chuot", "mouse"),
                sources_vi=_LAPTOP_AND_ACCESSORY_SOURCES,
                key_spec_fields=("connection", "dpi_max", "sensor", "buttons", "weight_g", "rgb"),
            ),
            CategoryProfile(
                category=Category.keyboard,
                label_vi="bàn phím",
                label_en="keyboards",
                detect_words=("ban phim", "keyboard"),
                sources_vi=_LAPTOP_AND_ACCESSORY_SOURCES,
                key_spec_fields=(
                    "connection",
                    "switch_type",
                    "switch_name",
                    "form_factor",
                    "hot_swap",
                    "backlight",
                ),
            ),
            CategoryProfile(
                category=Category.headset,
                label_vi="tai nghe",
                label_en="headsets",
                detect_words=("tai nghe", "headset", "headphone"),
                sources_vi=_LAPTOP_AND_ACCESSORY_SOURCES,
                key_spec_fields=(
                    "form",
                    "connection",
                    "has_mic",
                    "anc",
                    "surround_7_1",
                    "driver_mm",
                ),
            ),
            CategoryProfile(
                category=Category.phone,
                label_vi="điện thoại",
                label_en="phones",
                detect_words=("dien thoai", "smartphone", "iphone"),
                sources_vi="FPT Shop, Nguyễn Kim",
                key_spec_fields=(
                    "ram_gb",
                    "storage_gb",
                    "chipset",
                    "screen_in",
                    "battery_mah",
                    "os",
                ),
                name_style="capacity_variants",
            ),
        )
    }
)


def profile_of(category: Category | None) -> CategoryProfile | None:
    """Profile của nhóm tầng 1; None nếu nhóm chưa đăng ký (tầng 2, `other`) hoặc không có nhóm."""
    return CATEGORY_PROFILES.get(category) if category is not None else None


def registered_profiles() -> tuple[CategoryProfile, ...]:
    """Mọi profile theo thứ tự đăng ký."""
    return tuple(CATEGORY_PROFILES.values())


def tier1_categories() -> tuple[Category, ...]:
    """Các nhóm tầng 1 theo thứ tự đăng ký."""
    return tuple(CATEGORY_PROFILES)


def supported_names_vi() -> str:
    """ "laptop, chuột, bàn phím, tai nghe, điện thoại" (câu hỏi lại khi chưa rõ nhóm)."""
    return ", ".join(profile.label_vi for profile in registered_profiles())


def supported_names_en() -> str:
    """ "laptops, mice, keyboards, headsets and phones" (mô tả tool cho LLM)."""
    labels = [profile.label_en for profile in registered_profiles()]
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"
