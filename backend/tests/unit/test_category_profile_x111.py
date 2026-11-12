"""X1.11: khác biệt theo nhóm hàng gom vào `CategoryProfile` (`app/domain/categories.py`).

Đối chiếu: giá trị dựng từ profile trùng từng chữ với hằng viết tay trước X1.11 (không đổi hành
vi). Nhóm giả: đăng ký một profile là đủ để ý định, bước kế hoạch, câu "Chưa hỗ trợ…", thông số nổi
bật và LLM giả dùng được nhóm đó.
"""

from types import MappingProxyType

import pytest

from app.agent.fake_llm import CLARIFICATION, plan_from_text
from app.agent.intent import (
    DEFAULT_CLARIFICATION,
    SOURCES_BY_CATEGORY,
    TIER1_CATEGORIES,
    default_plan_steps,
    postprocess_intent,
)
from app.agent.tools.search_catalog import DESCRIPTION, SearchCatalogArgs
from app.domain import categories
from app.domain.categories import (
    CATEGORY_PROFILES,
    MAX_KEY_SPECS,
    CategoryProfile,
    profile_of,
    supported_names_en,
    supported_names_vi,
    tier1_categories,
)
from app.domain.dto import QueryIntent
from app.domain.enums import Category
from app.normalize.extract import _EXTRACTORS  # registry bộ trích xuất theo nhóm
from app.normalize.names import canonical_name
from app.normalize.specs import SPEC_MODELS
from app.services.rematch_service import REMATCH_CATEGORIES
from app.services.views import KEY_SPEC_FIELDS, key_specs

FIVE = (Category.laptop, Category.mouse, Category.keyboard, Category.headset, Category.phone)
ACCESSORY_SOURCES = "GearVN, FPT Shop, An Phát"


# ---- đối chiếu với hằng trước X1.11 ----
def test_tier1_categories_are_the_five_core_groups_in_order() -> None:
    assert tier1_categories() == FIVE
    assert frozenset(FIVE) == TIER1_CATEGORIES
    assert REMATCH_CATEGORIES == FIVE
    assert profile_of(Category.other) is None and profile_of(None) is None


def test_sources_by_category_are_unchanged() -> None:
    assert {
        Category.laptop: ACCESSORY_SOURCES,
        Category.mouse: ACCESSORY_SOURCES,
        Category.keyboard: ACCESSORY_SOURCES,
        Category.headset: ACCESSORY_SOURCES,
        Category.phone: "FPT Shop, Nguyễn Kim",
    } == SOURCES_BY_CATEGORY


def test_clarification_question_is_unchanged() -> None:
    expected = "Bạn muốn tìm loại sản phẩm nào (laptop, chuột, bàn phím, tai nghe, điện thoại…)?"
    assert expected == DEFAULT_CLARIFICATION
    assert expected == CLARIFICATION
    assert supported_names_vi() == "laptop, chuột, bàn phím, tai nghe, điện thoại"


@pytest.mark.parametrize(
    ("category", "label"),
    [
        (Category.laptop, "laptop"),
        (Category.mouse, "chuột"),
        (Category.keyboard, "bàn phím"),
        (Category.headset, "tai nghe"),
        (Category.phone, "điện thoại"),
        (Category.other, "sản phẩm"),
    ],
)
def test_default_plan_steps_name_the_category_in_vietnamese(category: Category, label: str) -> None:
    steps = default_plan_steps(QueryIntent(category=category))
    assert steps[0] == f"Tìm {label} trong danh mục đã thu thập"


def test_key_spec_fields_are_unchanged() -> None:
    assert dict(KEY_SPEC_FIELDS) == {
        Category.laptop: (
            "cpu_model",
            "gpu_model",
            "ram_gb",
            "storage_gb",
            "screen_in",
            "refresh_hz",
        ),
        Category.mouse: ("connection", "dpi_max", "sensor", "buttons", "weight_g", "rgb"),
        Category.keyboard: (
            "connection",
            "switch_type",
            "switch_name",
            "form_factor",
            "hot_swap",
            "backlight",
        ),
        Category.headset: ("form", "connection", "has_mic", "anc", "surround_7_1", "driver_mm"),
        Category.phone: ("ram_gb", "storage_gb", "chipset", "screen_in", "battery_mah", "os"),
    }


def test_search_catalog_schema_and_description_are_unchanged() -> None:
    schema = SearchCatalogArgs.model_json_schema()["properties"]["category"]
    assert schema == {
        "description": "Product category.",
        "enum": ["laptop", "mouse", "keyboard", "headset", "phone"],
        "title": "Category",
        "type": "string",
    }
    assert supported_names_en() == "laptops, mice, keyboards, headsets and phones"
    assert DESCRIPTION == (
        "Search the already-collected catalog of laptops, mice, keyboards, headsets and phones "
        "(tier 1 only) with price, brand, site, spec and keyword filters. Use for any shopping "
        "request in these five categories. Do NOT use for other product types "
        "(use live_search_other) and never invent products that are not returned."
    )


def test_search_catalog_rejects_a_category_without_profile() -> None:
    with pytest.raises(ValueError, match="'laptop', 'mouse', 'keyboard', 'headset', 'phone'"):
        SearchCatalogArgs.model_validate({"category": "other"})
    assert SearchCatalogArgs.model_validate({"category": "phone"}).category is Category.phone


def test_name_styles_match_the_previous_branches() -> None:
    styles = {profile.category: profile.name_style for profile in CATEGORY_PROFILES.values()}
    assert styles == {
        Category.laptop: "model_code",
        Category.mouse: "plain",
        Category.keyboard: "plain",
        Category.headset: "plain",
        Category.phone: "capacity_variants",
    }
    assert [c for c, p in CATEGORY_PROFILES.items() if p.uses_model_code] == [Category.laptop]
    # điện thoại: "+" rời là bản Plus, màu sau dung lượng bị bỏ; nhóm khác không áp dụng
    assert canonical_name("Samsung Galaxy S25 + 12 GB/256 GB Xanh", Category.phone) == (
        "Samsung Galaxy S25+ 12GB 256GB"
    )
    assert "+" not in canonical_name("Chuột Logitech G502 + Hero", Category.mouse)


# ---- mỗi profile khớp registry thông số / bộ trích xuất ở normalize ----
@pytest.mark.parametrize("category", FIVE)
def test_every_profile_has_a_spec_model_an_extractor_and_real_key_fields(
    category: Category,
) -> None:
    profile = profile_of(category)
    assert profile is not None and profile.category is category
    model = SPEC_MODELS[category]
    fields = set(model.model_fields) | set(model.model_computed_fields)
    assert set(profile.key_spec_fields) <= fields
    assert category in _EXTRACTORS
    assert len(profile.key_spec_fields) <= MAX_KEY_SPECS


def test_spec_registries_cover_exactly_the_profiles() -> None:
    assert set(SPEC_MODELS) == set(CATEGORY_PROFILES) == set(_EXTRACTORS)


def test_profiles_are_immutable_and_validated() -> None:
    profile = CATEGORY_PROFILES[Category.phone]
    with pytest.raises(ValueError):
        profile.label_vi = "x"
    with pytest.raises(ValueError):
        CategoryProfile(
            category=Category.other,
            label_vi="máy ảnh",
            label_en="cameras",
            detect_words=("may anh",),
            sources_vi="A",
            key_spec_fields=tuple(f"f{i}" for i in range(MAX_KEY_SPECS + 1)),
        )


# ---- đăng ký một nhóm giả là đủ ----
# Enum `Category` không thêm giá trị lúc chạy được (CHECK ở DB), nên nhóm giả mượn `Category.other`;
# chưa đăng ký thì `other` là đích tầng 2 (test cuối file).
CAMERA = CategoryProfile(
    category=Category.other,
    label_vi="máy ảnh",
    label_en="cameras",
    detect_words=("may anh",),
    sources_vi="Shop Ảnh Mock",
    key_spec_fields=("sensor_mp", "mount"),
)


@pytest.fixture
def camera_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        categories,
        "CATEGORY_PROFILES",
        MappingProxyType({**CATEGORY_PROFILES, Category.other: CAMERA}),
    )


@pytest.mark.usefixtures("camera_registered")
def test_a_registered_category_is_tier_one_with_its_own_steps_and_sources() -> None:
    intent = postprocess_intent(
        QueryIntent(category=Category.other, tier=1), "máy ảnh dưới 20 triệu trên Shopee"
    )

    assert intent.tier == 1 and intent.category is Category.other
    assert "Chưa hỗ trợ Shopee: tìm trên các nguồn hiện có (Shop Ảnh Mock)" in intent.plan_steps
    steps = default_plan_steps(QueryIntent(category=Category.other))
    assert steps[0] == "Tìm máy ảnh trong danh mục đã thu thập"
    assert supported_names_vi().endswith("điện thoại, máy ảnh")


@pytest.mark.usefixtures("camera_registered")
def test_a_registered_category_shows_its_key_specs_in_order() -> None:
    shown = key_specs(Category.other, {"weight_g": 500, "mount": "E", "sensor_mp": 24})
    assert shown == {"sensor_mp": 24, "mount": "E"}


@pytest.mark.usefixtures("camera_registered")
def test_the_fake_llm_detects_a_registered_category() -> None:
    assert plan_from_text("máy ảnh dưới 20 triệu").category is Category.other


def test_without_registration_the_same_category_stays_tier_two() -> None:
    intent = postprocess_intent(QueryIntent(category=Category.other, tier=1), "máy ảnh")
    assert intent.tier == 2
    assert key_specs(Category.other, {"weight_g": 500, "mount": "E"}) == {
        "weight_g": 500,
        "mount": "E",
    }
