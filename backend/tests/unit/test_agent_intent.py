"""T6.3: hậu xử lý QueryIntent (hàm thuần): tiền, "tầm", GPU → hạng, RAM, trang, hỏi lại."""

import pytest

from app.agent.intent import (
    DEFAULT_CLARIFICATION,
    default_plan_steps,
    extract_amounts,
    postprocess_intent,
)
from app.domain.dto import QueryIntent, SpecFilter
from app.domain.enums import Category, SiteKey


def intent(**fields: object) -> QueryIntent:
    return QueryIntent.model_validate({"plan_steps": ["Tìm trong danh mục"], **fields})


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("laptop dưới 30 triệu", {30_000_000}),
        ("laptop dưới 25tr card rtx4050, màn 144hz", {25_000_000}),
        ("tầm 2 triệu", {2_000_000}),
        ("giá 1,5tr", {1_500_000}),
        ("giá 1.5 triệu", {1_500_000}),
        ("khoảng 2tr5", {2_500_000}),
        ("chuột dưới 500k", {500_000}),
        ("tối đa 30m", {30_000_000}),
        ("giá 27.490.000đ", {27_490_000}),
        ("giá 27490000", {27_490_000}),
        ("từ 20 đến 30 triệu", {30_000_000}),
        ("ram 16gb ssd 1tb màn 165hz 27 inch", set()),
        ("RTX 4060 8GB 2K", set()),
        ("không có số", set()),
        ("", set()),
    ],
)
def test_extract_amounts(message: str, expected: set[int]) -> None:
    assert extract_amounts(message) == expected


def test_extract_amounts_collects_both_ends_of_a_range() -> None:
    assert extract_amounts("từ 20 triệu đến 30 triệu") == {20_000_000, 30_000_000}


def test_small_numbers_in_specs_are_not_money() -> None:
    assert extract_amounts("laptop 16gb ram 144hz 15.6 inch rtx 4060") == set()


@pytest.mark.parametrize(
    ("llm_value", "message", "expected"),
    [
        (30, "laptop dưới 30 triệu", 30_000_000),
        (30_000_000, "laptop dưới 30 triệu", 30_000_000),
        (500, "chuột dưới 500k", 500_000),
        (1, "chuột dưới 1 triệu", 1_000_000),
        (29_000_000, "laptop dưới 30 triệu", 29_000_000),  # không khớp số nào: giữ nguyên
        (30, "laptop gaming", 30),  # câu không có số tiền: không đoán
    ],
)
def test_price_max_unit_is_corrected_from_the_message(
    llm_value: int, message: str, expected: int
) -> None:
    result = postprocess_intent(intent(category="laptop", price_max=llm_value), message)
    assert result.price_max == expected


@pytest.mark.parametrize(
    ("given", "message", "expected"),
    [
        ({}, "laptop tầm 40 triệu", (36_000_000, 44_000_000)),
        ({"price_max": 40_000_000}, "laptop khoảng 40 triệu", (36_000_000, 44_000_000)),
        ({"price_min": 40_000_000}, "laptop tầm 40tr", (36_000_000, 44_000_000)),
        (
            {"price_min": 18_000_000, "price_max": 22_000_000},
            "tầm 20 triệu",
            (18_000_000, 22_000_000),
        ),
        ({}, "laptop dưới 40 triệu", (None, None)),
        ({"price_max": 40_000_000}, "laptop dưới 40 triệu", (None, 40_000_000)),
        ({}, "tầm 20 đến 30 triệu", (None, None)),  # hai số tiền: không phải "tầm một số"
    ],
)
def test_approximate_price_becomes_plus_minus_ten_percent(
    given: dict[str, int], message: str, expected: tuple[int | None, int | None]
) -> None:
    result = postprocess_intent(intent(category="laptop", **given), message)
    assert (result.price_min, result.price_max) == expected


def test_reversed_price_range_from_correction_is_swapped() -> None:
    result = postprocess_intent(
        intent(category="laptop", price_min=6, price_max=5_000_000), "từ 6 triệu đến 5 triệu"
    )
    assert (result.price_min, result.price_max) == (5_000_000, 6_000_000)


@pytest.mark.parametrize(
    ("raw_filter", "rank"),
    [
        ({"field": "gpu_model", "op": "eq", "value": "RTX 4060"}, 40),
        ({"field": "gpu", "op": "eq", "value": "GeForce RTX4070"}, 50),
        ({"field": "gpu_rank", "op": "eq", "value": "RTX 4060"}, 40),
        ({"field": "card", "op": "eq", "value": "rtx 3050 ti"}, 22),
    ],
)
def test_gpu_names_become_gpu_rank_filters(raw_filter: dict[str, object], rank: int) -> None:
    result = postprocess_intent(intent(category="laptop", spec_filters=[raw_filter]), "laptop")
    assert result.spec_filters == [SpecFilter(field="gpu_rank", op="gte", value=rank)]


def test_unknown_gpu_filter_is_dropped_instead_of_filtering_wrongly() -> None:
    bad = {"field": "gpu_model", "op": "eq", "value": "GTX 1650"}  # có tên nhưng chưa có hạng
    result = postprocess_intent(intent(category="laptop", spec_filters=[bad]), "laptop gtx 1650")
    assert result.spec_filters == []


def test_numeric_gpu_rank_filter_from_llm_is_kept() -> None:
    kept = {"field": "gpu_rank", "op": "gte", "value": 40}
    result = postprocess_intent(intent(category="laptop", spec_filters=[kept]), "rtx 4060")
    assert result.spec_filters == [SpecFilter(field="gpu_rank", op="gte", value=40)]


def test_gpu_named_in_message_but_missing_from_filters_is_added_for_laptops() -> None:
    result = postprocess_intent(intent(category="laptop"), "laptop gaming có card RTX 4060")
    assert result.spec_filters == [SpecFilter(field="gpu_rank", op="gte", value=40)]


def test_gpu_in_message_is_not_added_for_other_categories_or_when_unranked() -> None:
    assert postprocess_intent(intent(category="mouse"), "chuột rtx 4060").spec_filters == []
    assert postprocess_intent(intent(category="laptop"), "laptop gtx 1650").spec_filters == []


@pytest.mark.parametrize(
    ("message", "op"),
    [
        ("laptop ram 16gb", "gte"),
        ("laptop ram đúng 16gb", "eq"),
        ("laptop ram chính xác 16gb", "eq"),
    ],
)
def test_ram_is_at_least_unless_user_says_exact(message: str, op: str) -> None:
    given = {"field": "ram_gb", "op": "eq", "value": 16}
    result = postprocess_intent(intent(category="laptop", spec_filters=[given]), message)
    assert result.spec_filters == [SpecFilter(field="ram_gb", op=op, value=16)]  # type: ignore[arg-type]


def test_numeric_gpu_rank_eq_from_llm_becomes_at_least() -> None:
    given = {"field": "gpu_rank", "op": "eq", "value": 40}
    result = postprocess_intent(intent(category="laptop", spec_filters=[given]), "laptop rtx 4060")
    assert result.spec_filters == [SpecFilter(field="gpu_rank", op="gte", value=40)]


def test_other_eq_filters_are_left_alone() -> None:
    given = {"field": "switch_type", "op": "eq", "value": "mechanical"}
    result = postprocess_intent(intent(category="keyboard", spec_filters=[given]), "phím cơ")
    assert result.spec_filters == [SpecFilter(field="switch_type", op="eq", value="mechanical")]


@pytest.mark.parametrize(("given", "expected"), [(1, 1000), (2, 2000), (512, 512), (1000, 1000)])
def test_terabytes_become_gigabytes_only_when_the_message_says_tb(
    given: int, expected: int
) -> None:
    flt = {"field": "storage_gb", "op": "gte", "value": given}
    message = "laptop ssd 1tb" if given in (1, 2) else "laptop ssd 512gb"
    result = postprocess_intent(intent(category="laptop", spec_filters=[flt]), message)
    assert result.spec_filters[0].value == expected


def test_storage_one_without_tb_in_message_is_not_scaled() -> None:
    flt = {"field": "storage_gb", "op": "gte", "value": 1}
    result = postprocess_intent(intent(category="laptop", spec_filters=[flt]), "laptop ssd")
    assert result.spec_filters[0].value == 1


def test_unsupported_sites_are_dropped_and_explained_in_the_plan() -> None:
    given = intent(category="laptop", sites=[SiteKey.gearvn, SiteKey.viettelstore])

    result = postprocess_intent(given, "laptop trên GearVN và Shopee")

    assert result.sites == [SiteKey.gearvn]
    assert result.plan_steps[-1].startswith("Chưa hỗ trợ Shopee")


def test_mention_of_unsupported_site_is_not_explained_twice() -> None:
    given = intent(category="laptop", plan_steps=["Bỏ qua Tiki vì chưa hỗ trợ", "Tìm laptop"])
    result = postprocess_intent(given, "laptop trên Tiki")
    assert len(result.plan_steps) == 2


def test_two_unsupported_sites_are_listed_in_one_step() -> None:
    result = postprocess_intent(intent(category="laptop"), "laptop trên Tiki và Shopee")
    assert "Shopee, Tiki" in result.plan_steps[-1]


@pytest.mark.parametrize(
    "message", ["chuột logitech rẻ nhất", "chuot logitech re nhat", "giá thấp nhất"]
)
def test_cheapest_wording_sorts_by_price(message: str) -> None:
    assert postprocess_intent(intent(category="mouse"), message).sort == "price_asc"


def test_explicit_sort_from_llm_is_not_overridden() -> None:
    result = postprocess_intent(intent(category="mouse", sort="rating_desc"), "chuột rẻ nhất")
    assert result.sort == "rating_desc"


@pytest.mark.parametrize(
    ("given", "category", "tier"),
    [
        ({"category": "other", "tier": 1}, Category.other, 2),
        ({"category": "phone", "tier": 1}, Category.other, 2),
        ({"category": "laptop", "tier": 2}, Category.other, 2),
        ({"category": "mouse", "tier": 2}, Category.other, 2),
        ({"category": "mouse", "tier": 1}, Category.mouse, 1),
    ],
)
def test_tier_and_category_are_kept_consistent(
    given: dict[str, object], category: Category, tier: int
) -> None:
    result = postprocess_intent(intent(**given), "x")
    assert (result.category, result.tier) == (category, tier)


def test_clarification_flag_without_question_gets_the_default_question() -> None:
    result = postprocess_intent(intent(needs_clarification=True), "tìm cái nào rẻ rẻ")
    assert (result.needs_clarification, result.clarification_question) == (
        True,
        DEFAULT_CLARIFICATION,
    )


def test_clarification_question_is_kept_and_stripped() -> None:
    given = intent(needs_clarification=True, clarification_question="  Bạn cần loại nào?  ")
    assert postprocess_intent(given, "dưới 5 triệu").clarification_question == "Bạn cần loại nào?"


def test_stray_question_without_flag_is_removed() -> None:
    result = postprocess_intent(intent(clarification_question="Bạn cần gì?"), "x")
    assert (result.needs_clarification, result.clarification_question) == (False, None)


def test_missing_plan_steps_get_defaults_from_the_intent() -> None:
    given = intent(category="laptop", price_max=30_000_000, plan_steps=[])
    result = postprocess_intent(given, "laptop dưới 30 triệu")
    assert result.plan_steps == [
        "Tìm laptop trong danh mục đã thu thập",
        "Lọc theo giá dưới 30.000.000 ₫",
        "So sánh giá giữa các trang và trình bày bảng kết quả",
    ]


def test_plan_steps_are_trimmed_and_capped_at_five() -> None:
    steps = [f" bước {i} " for i in range(8)] + ["   "]
    result = postprocess_intent(intent(category="laptop", plan_steps=steps), "x")
    assert result.plan_steps == [f"bước {i}" for i in range(5)]


def test_default_steps_for_tier_two_and_unknown_category() -> None:
    assert default_plan_steps(intent(category="other", tier=2)) == [
        "Tìm trực tiếp sản phẩm ở các trang bán lẻ hỗ trợ tìm kiếm"
    ]
    assert default_plan_steps(intent())[0] == "Tìm sản phẩm trong danh mục đã thu thập"


def test_postprocess_does_not_mutate_the_input_and_is_idempotent() -> None:
    given = intent(
        category="laptop",
        price_max=30,
        spec_filters=[{"field": "gpu", "op": "eq", "value": "RTX 4060"}],
    )
    snapshot = given.model_copy(deep=True)

    once = postprocess_intent(given, "laptop dưới 30 triệu rtx 4060")
    twice = postprocess_intent(once, "laptop dưới 30 triệu rtx 4060")

    assert given == snapshot
    assert once == twice
