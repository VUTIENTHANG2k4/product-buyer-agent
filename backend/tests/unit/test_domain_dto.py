"""DTO miền (app/domain/dto.py): ràng buộc theo docs/04 §6."""

from typing import Any

import pytest
from pydantic import HttpUrl, ValidationError

from app.domain.dto import (
    Challenge,
    ListingItem,
    ListingPage,
    ProductDetail,
    QueryIntent,
    SpecFilter,
)
from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus


def _item(**overrides: Any) -> ListingItem:
    data: dict[str, Any] = {
        "site": "mockshop",
        "url": "https://mock.example/p/mock-laptop-1",
        "title": "Mock Laptop Gaming 15",
    }
    data.update(overrides)
    return ListingItem.model_validate(data)


# --- SpecFilter -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "value"),
    [
        ("eq", 16),
        ("gte", 16),
        ("lte", 2.5),
        ("contains", "wired"),
        ("contains_any", ["wired", "bluetooth"]),
        ("in", ["tkl", "75"]),
    ],
)
def test_spec_filter_accepts_every_documented_op(op: str, value: Any) -> None:
    assert SpecFilter.model_validate({"field": "x", "op": op, "value": value}).op == op


@pytest.mark.parametrize("op", ["like", "EQ", "gt", "", "neq"])
def test_spec_filter_rejects_unknown_op(op: str) -> None:
    with pytest.raises(ValidationError):
        SpecFilter.model_validate({"field": "ram_gb", "op": op, "value": 16})


@pytest.mark.parametrize("field", ["", "   "])
def test_spec_filter_rejects_blank_field_name(field: str) -> None:
    with pytest.raises(ValidationError):
        SpecFilter.model_validate({"field": field, "op": "eq", "value": 1})


@pytest.mark.parametrize(
    ("op", "value", "expected_type"),
    [
        ("eq", 40, int),
        ("eq", 2.5, float),
        ("eq", "RTX 4060", str),
        ("eq", True, bool),
        ("eq", False, bool),
        ("in", ["wired", "bluetooth"], list),
    ],
)
def test_spec_filter_keeps_value_type(op: str, value: Any, expected_type: type) -> None:
    parsed = SpecFilter.model_validate({"field": "x", "op": op, "value": value})
    assert type(parsed.value) is expected_type
    assert parsed.value == value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_spec_filter_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValidationError):
        SpecFilter.model_validate({"field": "x", "op": "gte", "value": value})


@pytest.mark.parametrize(
    ("op", "value"),
    [
        ("in", 5),
        ("in", "RTX"),
        ("contains_any", "wired"),
        ("gte", ["a"]),
        ("gte", "16"),
        ("gte", True),
        ("lte", ["1"]),
        ("eq", ["a"]),
        ("contains", ["a"]),
    ],
)
def test_spec_filter_rejects_value_that_does_not_fit_op(op: str, value: Any) -> None:
    with pytest.raises(ValidationError, match="requires"):
        SpecFilter.model_validate({"field": "x", "op": op, "value": value})


def test_spec_filter_rejects_list_of_numbers() -> None:
    with pytest.raises(ValidationError):
        SpecFilter.model_validate({"field": "x", "op": "in", "value": [1, 2]})


# --- QueryIntent ----------------------------------------------------------------------------


def test_empty_query_intent_uses_documented_defaults() -> None:
    intent = QueryIntent()
    assert intent.category is None
    assert intent.tier == 1
    assert intent.limit == 10
    assert intent.sort == "relevance"
    assert intent.needs_clarification is False
    assert intent.keywords == [] and intent.brands == [] and intent.sites == []
    assert intent.spec_filters == [] and intent.plan_steps == []


def test_query_intent_default_lists_are_not_shared() -> None:
    first, second = QueryIntent(), QueryIntent()
    first.keywords.append("gaming")
    assert second.keywords == []


@pytest.mark.parametrize("limit", [1, 10, 20])
def test_query_intent_accepts_limit_in_range(limit: int) -> None:
    assert QueryIntent(limit=limit).limit == limit


@pytest.mark.parametrize("limit", [-1, 0, 21, 100])
def test_query_intent_rejects_limit_out_of_range(limit: int) -> None:
    with pytest.raises(ValidationError):
        QueryIntent(limit=limit)


@pytest.mark.parametrize("tier", [0, 3, "x"])
def test_query_intent_rejects_unknown_tier(tier: Any) -> None:
    with pytest.raises(ValidationError):
        QueryIntent.model_validate({"tier": tier})


def test_query_intent_rejects_unknown_sort() -> None:
    with pytest.raises(ValidationError):
        QueryIntent.model_validate({"sort": "newest"})


def test_query_intent_rejects_inverted_price_range() -> None:
    with pytest.raises(ValidationError, match="price_min"):
        QueryIntent(price_min=20_000_000, price_max=10_000_000)


def test_query_intent_accepts_equal_and_open_ended_price_range() -> None:
    assert QueryIntent(price_min=5_000_000, price_max=5_000_000).price_max == 5_000_000
    assert QueryIntent(price_max=25_000_000).price_min is None
    assert QueryIntent(price_min=1_000_000).price_max is None


def test_query_intent_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        QueryIntent(price_max=-1)


def test_query_intent_round_trips_through_json() -> None:
    intent = QueryIntent(
        category=Category.laptop,
        keywords=["gaming"],
        price_max=25_000_000,
        brands=["ASUS"],
        sites=[SiteKey.gearvn],
        spec_filters=[SpecFilter(field="gpu_rank", op="gte", value=40)],
        sort="price_asc",
        limit=5,
        plan_steps=["Lọc laptop gaming dưới 25 triệu"],
    )
    restored = QueryIntent.model_validate(intent.model_dump(mode="json"))
    assert restored == intent
    assert restored.spec_filters[0].value == 40


def test_query_intent_parses_category_and_site_from_strings() -> None:
    intent = QueryIntent.model_validate({"category": "mouse", "sites": ["fptshop", "anphat"]})
    assert intent.category is Category.mouse
    assert intent.sites == [SiteKey.fptshop, SiteKey.anphat]


def test_query_intent_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        QueryIntent.model_validate({"category": "tablet"})


# --- ListingItem ----------------------------------------------------------------------------


def test_listing_item_minimal_uses_unknown_defaults() -> None:
    item = _item()
    assert item.site is SiteKey.mockshop
    assert item.price is None and item.list_price is None
    assert item.price_type is PriceType.unknown
    assert item.stock_status is StockStatus.unknown
    assert item.category_hint is Category.other
    assert item.raw_specs == {}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://mock.example/p/1", "http://mock.example/p/1"),
        ("https://gearvn.com/products/abc?variant=1", "https://gearvn.com/products/abc?variant=1"),
        ("HTTPS://Mock.Example/x", "https://mock.example/x"),  # scheme + host về chữ thường
        ("https://mock.example", "https://mock.example/"),  # URL chỉ có host thêm "/"
    ],
)
def test_listing_item_accepts_http_and_https_urls(url: str, expected: str) -> None:
    assert str(_item(url=url).url) == expected


def test_listing_item_does_not_strip_tracking_params() -> None:
    """Bỏ utm_*/fbclid là việc của `clean_url` (T2.5); DTO chỉ kiểm tra URL hợp lệ."""
    url = "https://mock.example/p/1?utm_source=x#frag"
    assert str(_item(url=url).url) == url


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "ftp://mock.example/file", "mock.example/p/1", "", "not a url", "/p/1"],
)
def test_listing_item_rejects_non_http_url(url: str) -> None:
    with pytest.raises(ValidationError):
        _item(url=url)


def test_listing_item_rejects_bad_image_url_but_allows_none() -> None:
    assert _item(image_url=None).image_url is None
    with pytest.raises(ValidationError):
        _item(image_url="data:image/png;base64,AAAA")


def test_listing_item_keeps_masked_price_as_none() -> None:
    assert _item(price=None, price_type="flash").price is None


def test_listing_item_keeps_integer_vnd_price() -> None:
    item = _item(price=27_490_000, list_price=29_990_000, price_type="sale")
    assert item.price == 27_490_000
    assert isinstance(item.price, int)
    assert item.price_type is PriceType.sale


def test_listing_item_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        _item(price=-1)
    with pytest.raises(ValidationError):
        _item(list_price=-5)


@pytest.mark.parametrize("price", [True, "27490000", 27_490_000.0])
def test_listing_item_rejects_price_that_is_not_a_real_int(price: Any) -> None:
    """Parser phải chuẩn hóa giá về int trước; bool/chuỗi/float không lọt qua."""
    with pytest.raises(ValidationError):
        _item(price=price)


@pytest.mark.parametrize("limit", [True, "5", 5.0])
def test_query_intent_rejects_limit_that_is_not_a_real_int(limit: Any) -> None:
    with pytest.raises(ValidationError):
        QueryIntent.model_validate({"limit": limit})


def test_listing_item_rejects_fractional_price() -> None:
    with pytest.raises(ValidationError):
        _item(price=27_490_000.5)


@pytest.mark.parametrize("rating", [-0.1, 5.1, 10])
def test_listing_item_rejects_rating_outside_zero_to_five(rating: float) -> None:
    with pytest.raises(ValidationError):
        _item(rating=rating)


@pytest.mark.parametrize("rating", [0, 4.5, 5])
def test_listing_item_accepts_rating_in_range(rating: float) -> None:
    assert _item(rating=rating).rating == rating


def test_listing_item_rejects_negative_rating_count() -> None:
    with pytest.raises(ValidationError):
        _item(rating_count=-1)


@pytest.mark.parametrize("title", ["", "   ", "\n\t"])
def test_listing_item_rejects_blank_title(title: str) -> None:
    with pytest.raises(ValidationError):
        _item(title=title)


def test_listing_item_strips_title_whitespace() -> None:
    assert _item(title="  Mock Laptop  ").title == "Mock Laptop"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("site", "shopee"),
        ("price_type", "discount"),
        ("stock_status", "available"),
        ("category_hint", "tablet"),
    ],
)
def test_listing_item_rejects_unknown_enum_value(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _item(**{field: value})


def test_listing_item_rejects_non_string_raw_spec_values() -> None:
    with pytest.raises(ValidationError):
        _item(raw_specs={"RAM": ["16GB"]})


def test_listing_item_raw_specs_default_is_not_shared() -> None:
    first, second = _item(), _item()
    first.raw_specs["RAM"] = "16GB"
    assert second.raw_specs == {}


def test_listing_item_round_trips_through_json() -> None:
    item = _item(
        price=18_990_000,
        list_price=20_990_000,
        price_type="sale",
        stock_status="in_stock",
        image_url="https://mock.example/i/1.jpg",
        rating=4.5,
        rating_count=12,
        site_sku="MOCK-1",
        raw_specs={"RAM": "16GB"},
        category_hint="laptop",
    )
    assert ListingItem.model_validate(item.model_dump(mode="json")) == item


# --- ListingPage / ProductDetail ------------------------------------------------------------


def test_listing_page_defaults_to_empty_last_page() -> None:
    page = ListingPage()
    assert page.items == [] and page.has_next is False and page.next_url is None


def test_listing_page_holds_items_and_next_url() -> None:
    page = ListingPage(
        items=[_item()], has_next=True, next_url=HttpUrl("https://mock.example/laptop?page=2")
    )
    assert len(page.items) == 1
    assert str(page.next_url) == "https://mock.example/laptop?page=2"


def test_listing_page_rejects_bad_next_url() -> None:
    with pytest.raises(ValidationError):
        ListingPage.model_validate({"items": [], "has_next": True, "next_url": "page=2"})


def test_listing_page_rejects_item_with_bad_url() -> None:
    with pytest.raises(ValidationError):
        ListingPage.model_validate(
            {"items": [{"site": "mockshop", "url": "nope", "title": "x"}], "has_next": False}
        )


def test_product_detail_requires_valid_url_and_defaults_hints_to_none() -> None:
    detail = ProductDetail.model_validate({"url": "https://mock.example/p/1"})
    assert detail.raw_specs == {} and detail.model_code_hint is None and detail.brand_hint is None
    with pytest.raises(ValidationError):
        ProductDetail.model_validate({"url": "ftp://mock.example/p/1"})
    with pytest.raises(ValidationError):
        ProductDetail.model_validate({})


def test_product_detail_round_trips_through_json() -> None:
    detail = ProductDetail.model_validate(
        {
            "url": "https://mock.example/p/1",
            "raw_specs": {"CPU": "Intel Core i7-13620H"},
            "model_code_hint": "FX608JHI-TU209W",
            "brand_hint": "ASUS",
        }
    )
    assert ProductDetail.model_validate(detail.model_dump(mode="json")) == detail


# --- Challenge ------------------------------------------------------------------------------


def test_challenge_roundtrips_through_json_for_scrape_run_storage() -> None:
    challenge = Challenge(
        kind=ChallengeKind.captcha,
        site=SiteKey.mockshop,
        url=HttpUrl("http://127.0.0.1:8100/c/laptop"),
        prompt="AB3XZ",
        token="tok-1",
    )
    stored = challenge.model_dump(mode="json")
    assert stored["kind"] == "captcha"
    assert stored["site"] == "mockshop"
    assert Challenge.model_validate(stored) == challenge


def test_challenge_optional_fields_default_to_none() -> None:
    challenge = Challenge.model_validate(
        {"kind": "http_403", "site": "gearvn", "url": "https://gearvn.example/"}
    )
    assert (challenge.prompt, challenge.image_url, challenge.token) == (None, None, None)


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "captcha!", "site": "gearvn", "url": "https://gearvn.example/"},
        {"kind": "captcha", "site": "shopee", "url": "https://gearvn.example/"},
        {"kind": "captcha", "site": "gearvn", "url": "not a url"},
        {"kind": "captcha", "site": "gearvn", "url": "https://gearvn.example/", "image_url": "x"},
    ],
)
def test_challenge_rejects_invalid_values(bad: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Challenge.model_validate(bad)
