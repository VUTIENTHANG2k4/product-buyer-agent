"""QA M1: test biên cho `ProductRepository.search` và `spec_condition` (docs/04 §3, §4)."""

from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.db.models import Product
from app.db.repositories.offers import OfferRepository, OfferUpsert
from app.db.repositories.products import ProductQuery, ProductRepository
from app.domain.dto import SpecFilter
from app.domain.enums import PriceType, SiteKey, StockStatus
from app.normalize.specs.laptop import LaptopSpecs
from tests.factories import make_product


def _add(session: Session, **overrides: Any) -> Product:
    return ProductRepository(session).add(make_product(**overrides))


def _offer(session: Session, product: Product, url: str, **overrides: Any) -> None:
    assert product.id is not None
    values: dict[str, Any] = {
        "product_id": product.id,
        "site": SiteKey.mockshop,
        "url": url,
        "title": product.canonical_name,
        "price": 20_000_000,
    }
    values.update(overrides)
    OfferRepository(session).upsert(OfferUpsert.model_validate(values))


def _spec(field: str, op: str, value: Any) -> SpecFilter:
    return SpecFilter.model_validate({"field": field, "op": op, "value": value})


def _names(session: Session, **query: Any) -> list[str]:
    page = ProductRepository(session).search(ProductQuery.model_validate(query))
    return [hit.product.canonical_name for hit in page.items]


# --- SpecFilter -> JSONB: giá trị sai kiểu, bool, list, object --------------------------------

MIXED_TYPE_SPECS: list[tuple[str, dict[str, Any]]] = [
    ("Mock Int", {"x": 16}),
    ("Mock Float", {"x": 16.5}),
    ("Mock Text", {"x": "16GB"}),
    ("Mock NumText", {"x": "16"}),
    ("Mock Null", {"x": None}),
    ("Mock True", {"x": True}),
    ("Mock False", {"x": False}),
    ("Mock List", {"x": [16, 32]}),
    ("Mock Object", {"x": {"gb": 16}}),
    ("Mock Zero", {"x": 0}),
    ("Mock Negative", {"x": -4}),
    ("Mock Missing", {"y": 16}),
]


@pytest.fixture
def mixed_catalog(db_session: Session) -> None:
    for index, (name, specs) in enumerate(MIXED_TYPE_SPECS):
        product = _add(db_session, canonical_name=name, specs=specs)
        _offer(db_session, product, f"https://m.example/mixed/{index}")


@pytest.mark.usefixtures("mixed_catalog")
@pytest.mark.parametrize(
    ("spec_filter", "expected"),
    [
        # Chỉ số JSON thật sự là number mới được so sánh bằng số; bool/chuỗi/list/object thì không.
        pytest.param(_spec("x", "gte", 0), {"Mock Int", "Mock Float", "Mock Zero"}, id="gte-0"),
        pytest.param(
            _spec("x", "gte", -10),
            {"Mock Int", "Mock Float", "Mock Zero", "Mock Negative"},
            id="gte-negative",
        ),
        pytest.param(
            _spec("x", "lte", 16), {"Mock Int", "Mock Zero", "Mock Negative"}, id="lte-16"
        ),
        pytest.param(_spec("x", "eq", 16), {"Mock Int"}, id="eq-16-not-bool-not-text"),
        pytest.param(_spec("x", "eq", 0), {"Mock Zero"}, id="eq-0-is-not-false-or-null"),
        pytest.param(_spec("x", "eq", 1), set(), id="eq-1-does-not-match-true"),
        pytest.param(_spec("x", "eq", True), {"Mock True"}, id="eq-true"),
        pytest.param(_spec("x", "eq", False), {"Mock False"}, id="eq-false-is-not-zero-or-missing"),
        pytest.param(_spec("x", "gte", 16.25), {"Mock Float"}, id="gte-float"),
    ],
)
def test_search_spec_filter_ignores_values_of_another_json_type(
    db_session: Session, spec_filter: SpecFilter, expected: set[str]
) -> None:
    names = _names(db_session, spec_filters=[spec_filter])

    assert set(names) == expected
    assert len(names) == len(expected)


@pytest.mark.usefixtures("mixed_catalog")
@pytest.mark.parametrize(
    ("spec_filter", "expected"),
    [
        pytest.param(_spec("x", "contains", 16), {"Mock List"}, id="contains-number-in-list"),
        pytest.param(_spec("x", "contains", "16"), set(), id="contains-text-does-not-match-number"),
        pytest.param(
            _spec("x", "contains_any", ["16", "32"]), set(), id="contains-any-text-vs-numbers"
        ),
        pytest.param(_spec("x", "contains", 64), set(), id="contains-absent-value"),
        pytest.param(_spec("y", "contains", 16), set(), id="contains-on-scalar-field"),
        pytest.param(
            _spec("x", "in", ["16", "16GB"]),
            {"Mock Int", "Mock Text", "Mock NumText"},
            id="in-compares-text-form",
        ),
        pytest.param(_spec("x", "eq", "16GB"), {"Mock Text"}, id="eq-text"),
    ],
)
def test_search_spec_filter_list_and_text_operators_on_mixed_types(
    db_session: Session, spec_filter: SpecFilter, expected: set[str]
) -> None:
    assert set(_names(db_session, spec_filters=[spec_filter])) == expected


def test_search_spec_filter_on_float_value_matches_the_same_decimal(db_session: Session) -> None:
    for name, screen in (("Mock 15", 15.6), ("Mock 14", 14.0), ("Mock 16", 16.1)):
        _offer(
            db_session,
            _add(db_session, canonical_name=name, specs={"screen_in": screen}),
            f"https://m.example/{name}",
        )

    assert _names(db_session, spec_filters=[_spec("screen_in", "eq", 15.6)]) == ["Mock 15"]
    assert _names(db_session, spec_filters=[_spec("screen_in", "lte", 14)]) == ["Mock 14"]
    assert set(_names(db_session, spec_filters=[_spec("screen_in", "gte", 15.6)])) == {
        "Mock 15",
        "Mock 16",
    }


def test_search_by_gpu_rank_uses_the_real_laptop_specs_dump(db_session: Session) -> None:
    """`LaptopSpecs.model_dump` (có `gpu_rank: null` khi GPU chưa có hạng) đi qua bộ lọc JSONB."""
    gpus = {
        "Mock Integrated": "Radeon Graphics",
        "Mock 4060": "GeForce RTX4060 8GB",
        "Mock 5070 Ti": "RTX 5070 Ti",
        "Mock GTX": "GTX 1650",  # chưa có hạng: gpu_rank = null
        "Mock 4060 Ti": "RTX 4060 Ti",  # chưa có hạng
        "Mock NoGpu": None,
    }
    for index, (name, gpu) in enumerate(gpus.items()):
        specs = LaptopSpecs(ram_gb=16, gpu_model=gpu).model_dump(mode="json")
        _offer(
            db_session,
            _add(db_session, canonical_name=name, specs=specs),
            f"https://m.example/gpu/{index}",
        )

    def names(op: str, value: int) -> set[str]:
        return set(_names(db_session, spec_filters=[_spec("gpu_rank", op, value)]))

    assert names("gte", 40) == {"Mock 4060", "Mock 5070 Ti"}
    assert names("gte", 0) == {"Mock Integrated", "Mock 4060", "Mock 5070 Ti"}
    assert names("lte", 40) == {"Mock Integrated", "Mock 4060"}
    assert names("eq", 0) == {"Mock Integrated"}  # hạng 0 không bị coi là thiếu


# --- Giá hiệu lực, offer ngừng bán, biên của bộ lọc giá ---------------------------------------


@pytest.mark.parametrize(
    ("price_type", "list_price", "effective"),
    [
        (PriceType.regular, None, 18_000_000),
        (PriceType.regular, 25_000_000, 18_000_000),
        (PriceType.sale, 25_000_000, 18_000_000),
        (PriceType.flash, 25_000_000, 18_000_000),
        (PriceType.unknown, 25_000_000, 18_000_000),
        (PriceType.member, 25_000_000, 25_000_000),
        (PriceType.member, None, 18_000_000),  # không có giá niêm yết thì dùng chính giá thành viên
    ],
)
def test_search_min_price_is_the_effective_price_of_the_offer(
    db_session: Session, price_type: PriceType, list_price: int | None, effective: int
) -> None:
    product = _add(db_session)
    _offer(
        db_session,
        product,
        "https://m.example/eff",
        price=18_000_000,
        list_price=list_price,
        price_type=price_type,
    )

    page = ProductRepository(db_session).search(ProductQuery())

    assert [(hit.min_price, hit.max_price) for hit in page.items] == [(effective, effective)]


def test_search_price_bounds_are_inclusive(db_session: Session) -> None:
    product = _add(db_session, canonical_name="Mock Edge")
    _offer(db_session, product, "https://m.example/edge", price=20_000_000)

    assert _names(db_session, price_min=20_000_000, price_max=20_000_000) == ["Mock Edge"]
    assert _names(db_session, price_max=19_999_999) == []
    assert _names(db_session, price_min=20_000_001) == []
    assert _names(db_session, price_min=0, price_max=0) == []


def test_search_with_inverted_price_range_returns_nothing_instead_of_failing(
    db_session: Session,
) -> None:
    _offer(db_session, _add(db_session), "https://m.example/inv")

    page = ProductRepository(db_session).search(
        ProductQuery(price_min=30_000_000, price_max=10_000_000)
    )

    assert (page.total, page.items) == (0, [])


def test_search_price_filter_ignores_inactive_offers(db_session: Session) -> None:
    product = _add(db_session, canonical_name="Mock Switched")
    _offer(db_session, product, "https://m.example/cheap", price=10_000_000)
    _offer(db_session, product, "https://m.example/dear", price=30_000_000)
    cheap = OfferRepository(db_session).get_by_url("https://m.example/cheap")
    assert cheap is not None
    cheap.is_active = False
    db_session.flush()

    assert _names(db_session, price_max=20_000_000) == []
    page = ProductRepository(db_session).search(ProductQuery(price_max=40_000_000))
    assert [(hit.min_price, hit.offers_count) for hit in page.items] == [(30_000_000, 1)]


def test_search_counts_out_of_stock_offers_like_any_active_offer(db_session: Session) -> None:
    """Ghi nhận hành vi hiện tại: `stock_status` không ảnh hưởng `search` (xem báo cáo QA M1)."""
    product = _add(db_session)
    _offer(
        db_session,
        product,
        "https://m.example/oos",
        price=15_000_000,
        stock_status=StockStatus.out_of_stock,
    )
    _offer(db_session, product, "https://m.example/in", price=20_000_000)

    hit = ProductRepository(db_session).search(ProductQuery()).items[0]

    assert (hit.min_price, hit.offers_count) == (15_000_000, 2)


# --- Phân trang, sắp xếp, tổng khi limit/offset ngoài miền ------------------------------------


@pytest.mark.parametrize("sort", ["price_asc", "price_desc", "rating_desc"])
def test_search_pages_of_equal_keys_neither_overlap_nor_skip(
    db_session: Session, sort: str
) -> None:
    created = []
    for index in range(7):
        product = _add(db_session, canonical_name=f"Mock Tie {index}")
        _offer(db_session, product, f"https://m.example/tie/{index}", price=20_000_000, rating=4.0)
        created.append(product.canonical_name)
    repo = ProductRepository(db_session)

    seen: list[str] = []
    for offset in (0, 3, 6, 9):
        page = repo.search(ProductQuery(sort=sort, limit=3, offset=offset))  # type: ignore[arg-type]
        assert page.total == 7
        seen.extend(hit.product.canonical_name for hit in page.items)

    assert sorted(seen) == sorted(created)
    assert len(seen) == len(set(seen)) == 7


def test_search_offset_at_or_beyond_total_returns_empty_page_with_total(
    db_session: Session,
) -> None:
    for index in range(3):
        _offer(db_session, _add(db_session), f"https://m.example/page/{index}")
    repo = ProductRepository(db_session)

    for offset in (3, 4, 2**31):
        page = repo.search(ProductQuery(offset=offset))
        assert (page.total, page.items) == (3, [])
    assert len(repo.search(ProductQuery(limit=100)).items) == 3
    assert len(repo.search(ProductQuery(limit=1, offset=2)).items) == 1


def test_search_rating_desc_breaks_ties_by_cheapest_then_by_id(db_session: Session) -> None:
    rows = [
        ("Mock Rated Dear", 4.5, 30_000_000),
        ("Mock Rated Cheap", 4.5, 10_000_000),
        ("Mock Unrated Cheapest", None, 5_000_000),
        ("Mock Top", 5.0, 40_000_000),
    ]
    for index, (name, rating, price) in enumerate(rows):
        product = _add(db_session, canonical_name=name)
        _offer(db_session, product, f"https://m.example/r/{index}", price=price, rating=rating)

    assert _names(db_session, sort="rating_desc") == [
        "Mock Top",
        "Mock Rated Cheap",
        "Mock Rated Dear",
        "Mock Unrated Cheapest",
    ]


def test_search_rating_uses_the_best_rating_over_active_offers_only(db_session: Session) -> None:
    product = _add(db_session)
    _offer(db_session, product, "https://m.example/a", rating=3.5)
    _offer(db_session, product, "https://m.example/b", rating=4.9)
    best = OfferRepository(db_session).get_by_url("https://m.example/b")
    assert best is not None
    best.is_active = False
    db_session.flush()

    hit = ProductRepository(db_session).search(ProductQuery()).items[0]

    assert hit.best_rating == 3.5


# --- Dữ liệu cực trị trong ProductQuery -------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        pytest.param({"price_max": 10**30}, id="price_max"),
        pytest.param({"price_min": 10**30}, id="price_min"),
        pytest.param({"offset": 10**20}, id="offset"),
        pytest.param({"spec_filters": [{"field": "ram_gb", "op": "gte", "value": 10**30}]}, id="spec-value"),
    ],
)
def test_search_with_integers_beyond_bigint_is_rejected_or_answered_not_crashed(
    db_session: Session, query: dict[str, Any]
) -> None:
    _offer(db_session, _add(db_session, specs={"ram_gb": 16}), "https://m.example/big")
    try:
        built = ProductQuery.model_validate(query)
    except ValueError:
        return  # từ chối ngay khi dựng truy vấn là cách xử lý chấp nhận được

    try:
        ProductRepository(db_session).search(built)
    except DBAPIError as error:  # pragma: no cover - đường lỗi hiện tại
        pytest.fail(f"search ném lỗi CSDL thay vì xử lý: {type(error).__name__}")


def test_search_with_int8_max_values_does_not_crash(db_session: Session) -> None:
    _offer(db_session, _add(db_session), "https://m.example/int8")
    biggest = 2**63 - 1

    page = ProductRepository(db_session).search(
        ProductQuery(price_min=0, price_max=biggest, offset=biggest)
    )

    assert (page.total, page.items) == (1, [])


def test_search_extreme_price_is_returned_exactly(db_session: Session) -> None:
    product = _add(db_session)
    _offer(db_session, product, "https://m.example/extreme", price=2**63 - 1)

    hit = ProductRepository(db_session).search(ProductQuery(price_min=2**62)).items[0]

    assert (hit.min_price, hit.max_price) == (2**63 - 1, 2**63 - 1)


# --- update_specs ------------------------------------------------------------------------------


def test_update_specs_applies_zero_confidence_and_copies_the_dict(db_session: Session) -> None:
    repo = ProductRepository(db_session)
    product = _add(db_session, specs={"ram_gb": 8})
    given: dict[str, Any] = {"ram_gb": 16, "tags": ["a"]}

    repo.update_specs(product, given, specs_confidence=0.0)
    given["ram_gb"] = 999  # sửa dict của người gọi sau đó không được lọt vào DB
    db_session.flush()
    db_session.expire(product)

    assert product.specs == {"ram_gb": 16, "tags": ["a"]}
    assert product.specs_confidence == 0.0


def test_update_specs_with_empty_dict_clears_specs(db_session: Session) -> None:
    product = _add(db_session, specs={"ram_gb": 8})

    ProductRepository(db_session).update_specs(product, {})
    db_session.expire(product)

    assert product.specs == {}


def test_search_brand_filter_ignores_blank_brand_entries_without_matching_everything(
    db_session: Session,
) -> None:
    _offer(
        db_session,
        _add(db_session, canonical_name="Mock Asus", brand="ASUS"),
        "https://m.example/brand",
    )
    _offer(
        db_session,
        _add(db_session, canonical_name="Mock Acer", brand="Acer"),
        "https://m.example/brand2",
    )

    assert _names(db_session, brands=[""]) == []
    assert _names(db_session, brands=["ASUS", ""]) == ["Mock Asus"]
