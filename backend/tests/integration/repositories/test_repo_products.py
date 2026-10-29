from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.models import Product
from app.db.repositories.offers import OfferRepository, OfferUpsert
from app.db.repositories.products import ProductQuery, ProductRepository
from app.domain.dto import SpecFilter
from app.domain.enums import Category, PriceType, SiteKey
from tests.factories import make_product


def _add(session: Session, **overrides: Any) -> Product:
    return ProductRepository(session).add(make_product(**overrides))


def _offer(session: Session, product: Product, **overrides: Any) -> None:
    assert product.id is not None
    values: dict[str, Any] = {
        "product_id": product.id,
        "site": SiteKey.mockshop,
        "url": f"https://mock.example/{product.id}/{len(overrides)}/{overrides.get('price')}",
        "title": product.canonical_name,
        "price": 20_000_000,
    }
    values.update(overrides)
    OfferRepository(session).upsert(OfferUpsert.model_validate(values))


def _names(session: Session, **query: Any) -> list[str]:
    page = ProductRepository(session).search(ProductQuery.model_validate(query))
    return [hit.product.canonical_name for hit in page.items]


def _spec(field: str, op: str, value: Any) -> SpecFilter:
    return SpecFilter.model_validate({"field": field, "op": op, "value": value})


def test_add_get_and_get_many_keep_requested_order(db_session: Session) -> None:
    repo = ProductRepository(db_session)
    first, second = _add(db_session), _add(db_session)
    assert first.id is not None and second.id is not None

    assert repo.get(first.id) is first
    assert repo.get(999_999_999) is None
    assert repo.get_many([second.id, 999_999_999, first.id]) == [second, first]
    assert repo.get_many([]) == []


def test_find_by_model_key_matches_category_brand_and_code(db_session: Session) -> None:
    repo = ProductRepository(db_session)
    product = _add(db_session, brand="ASUS", model_code="FX608JHI")

    assert repo.find_by_model_key(Category.laptop, "ASUS", "FX608JHI") is product
    assert repo.find_by_model_key(Category.laptop, "Acer", "FX608JHI") is None
    assert repo.find_by_model_key(Category.mouse, "ASUS", "FX608JHI") is None
    assert repo.find_by_model_key(Category.laptop, "ASUS", "OTHER") is None


def test_add_duplicate_model_key_is_rejected_by_partial_unique_index(db_session: Session) -> None:
    _add(db_session, brand="ASUS", model_code="DUP-1")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        _add(db_session, brand="ASUS", model_code="DUP-1")


def test_update_specs_replaces_dict_and_confidence(db_session: Session) -> None:
    repo = ProductRepository(db_session)
    product = _add(db_session, specs={"ram_gb": 8})

    repo.update_specs(product, {"ram_gb": 32, "gpu_rank": 50}, specs_confidence=0.4)
    db_session.expire(product)

    assert product.specs == {"ram_gb": 32, "gpu_rank": 50}
    assert product.specs_confidence == 0.4
    repo.update_specs(product, {"ram_gb": 16})
    assert product.specs == {"ram_gb": 16}
    assert product.specs_confidence == 0.4


def test_set_image_url_persists_the_new_image(db_session: Session) -> None:
    repo = ProductRepository(db_session)
    product = _add(db_session, image_url=None)

    repo.set_image_url(product, "https://img.example/a.jpg")
    db_session.expire(product)

    assert product.image_url == "https://img.example/a.jpg"


def test_search_excludes_products_without_active_offers(db_session: Session) -> None:
    sold = _add(db_session, canonical_name="Mock Sold")
    _add(db_session, canonical_name="Mock No Offer")
    gone = _add(db_session, canonical_name="Mock Gone")
    _offer(db_session, sold)
    _offer(db_session, gone)
    gone_offer = OfferRepository(db_session).list_for_product(gone.id or 0)[0]
    gone_offer.is_active = False
    db_session.flush()

    assert _names(db_session) == ["Mock Sold"]


def test_search_aggregates_prices_over_active_offers(db_session: Session) -> None:
    product = _add(db_session)
    _offer(db_session, product, url="https://m.example/1", price=30_000_000, rating=4.0)
    _offer(db_session, product, url="https://m.example/2", price=25_000_000, rating=4.8)
    _offer(
        db_session,
        product,
        url="https://m.example/3",
        price=22_000_000,
        list_price=28_000_000,
        price_type=PriceType.member,
    )

    _offer(db_session, product, url="https://m.example/4", price=1_000_000)
    cheapest = OfferRepository(db_session).get_by_url("https://m.example/4")
    assert cheapest is not None
    cheapest.is_active = False  # offer đã tắt không được tính vào min/count
    db_session.flush()
    _offer(db_session, product, url="https://g.example/5", price=40_000_000, site=SiteKey.gearvn)
    repo = ProductRepository(db_session)

    page = repo.search(ProductQuery(sites=[SiteKey.mockshop]))

    assert page.total == 1
    hit = page.items[0]
    assert (hit.min_price, hit.max_price, hit.offers_count) == (25_000_000, 30_000_000, 3)
    assert hit.best_rating == 4.8
    all_sites = repo.search(ProductQuery()).items[0]
    assert (all_sites.max_price, all_sites.offers_count) == (40_000_000, 4)


def test_search_price_range_uses_effective_price_per_offer(db_session: Session) -> None:
    both = _add(db_session, canonical_name="Mock Both")
    member_only = _add(db_session, canonical_name="Mock Member")
    _offer(db_session, both, url="https://m.example/b1", price=18_000_000)
    _offer(db_session, both, url="https://m.example/b2", price=35_000_000)
    # giá thành viên 15 triệu nhưng so sánh bằng giá niêm yết 31 triệu
    _offer(
        db_session,
        member_only,
        url="https://m.example/m1",
        price=15_000_000,
        list_price=31_000_000,
        price_type=PriceType.member,
    )

    page = ProductRepository(db_session).search(ProductQuery(price_max=30_000_000))

    assert [hit.product.canonical_name for hit in page.items] == ["Mock Both"]
    assert (page.items[0].min_price, page.items[0].offers_count) == (18_000_000, 1)
    assert _names(db_session, price_min=30_000_000) == ["Mock Member", "Mock Both"]
    assert _names(db_session, price_min=40_000_000) == []


def test_search_filters_by_site_category_and_brand_case_insensitively(db_session: Session) -> None:
    gear = _add(db_session, canonical_name="Mock Gear", brand="ASUS")
    mock = _add(db_session, canonical_name="Mock Shop", brand="Acer")
    mouse = _add(db_session, canonical_name="Mock Mouse", category=Category.mouse, brand="ASUS")
    _offer(db_session, gear, site=SiteKey.gearvn)
    _offer(db_session, mock, site=SiteKey.mockshop)
    _offer(db_session, mouse, site=SiteKey.gearvn)

    assert _names(db_session, sites=["gearvn"], category="laptop") == ["Mock Gear"]
    assert _names(db_session, brands=["asus"], category="laptop") == ["Mock Gear"]
    assert sorted(_names(db_session, brands=["ASUS", "acer"])) == [
        "Mock Gear",
        "Mock Mouse",
        "Mock Shop",
    ]
    assert _names(db_session, category="headset") == []


def test_search_sorts_and_paginates(db_session: Session) -> None:
    cheap = _add(db_session, canonical_name="Mock Cheap")
    mid = _add(db_session, canonical_name="Mock Mid")
    dear = _add(db_session, canonical_name="Mock Dear")
    _offer(db_session, cheap, price=10_000_000, rating=3.0)
    _offer(db_session, mid, price=20_000_000)
    _offer(db_session, dear, price=30_000_000, rating=4.9)
    repo = ProductRepository(db_session)

    assert _names(db_session, sort="price_asc") == ["Mock Cheap", "Mock Mid", "Mock Dear"]
    assert _names(db_session, sort="price_desc") == ["Mock Dear", "Mock Mid", "Mock Cheap"]
    assert _names(db_session, sort="rating_desc") == ["Mock Dear", "Mock Cheap", "Mock Mid"]
    page = repo.search(ProductQuery(limit=1, offset=1))
    assert page.total == 3
    assert [hit.product.canonical_name for hit in page.items] == ["Mock Mid"]


@pytest.fixture
def specs_catalog(db_session: Session) -> None:
    rows: list[tuple[str, dict[str, Any]]] = [
        ("Mock A", {"gpu_rank": 40, "ram_gb": 16, "is_gaming": True, "screen_in": 15.6}),
        ("Mock B", {"gpu_rank": 50, "ram_gb": 32, "is_gaming": True, "screen_in": 16.0}),
        ("Mock C", {"gpu_rank": 0, "ram_gb": 8, "is_gaming": False}),
        ("Mock D", {"ram_gb": 16}),  # thiếu gpu_rank
        ("Mock E", {"gpu_rank": None, "ram_gb": "16GB"}),  # sai kiểu / null
    ]
    for name, specs in rows:
        product = _add(db_session, canonical_name=name, specs=specs)
        _offer(db_session, product)


@pytest.mark.usefixtures("specs_catalog")
@pytest.mark.parametrize(
    ("spec_filter", "expected"),
    [
        (_spec("gpu_rank", "gte", 40), {"Mock A", "Mock B"}),
        (_spec("gpu_rank", "gte", 41), {"Mock B"}),
        (_spec("gpu_rank", "lte", 40), {"Mock A", "Mock C"}),
        (_spec("ram_gb", "gte", 16), {"Mock A", "Mock B", "Mock D"}),
        (_spec("ram_gb", "eq", 16), {"Mock A", "Mock D"}),
        (_spec("screen_in", "gte", 15.6), {"Mock A", "Mock B"}),
        (_spec("screen_in", "eq", 16), {"Mock B"}),
        (_spec("is_gaming", "eq", True), {"Mock A", "Mock B"}),
        (_spec("is_gaming", "eq", False), {"Mock C"}),
        (_spec("ghost_field", "gte", 0), set()),
        (_spec("ram_gb", "in", ["8", "32"]), {"Mock B", "Mock C"}),
        (_spec("gpu_rank", "eq", 40), {"Mock A"}),
    ],
)
def test_search_spec_filter_scalar_operators(
    db_session: Session, spec_filter: SpecFilter, expected: set[str]
) -> None:
    names = _names(db_session, spec_filters=[spec_filter])

    assert set(names) == expected
    assert len(names) == len(expected)


@pytest.mark.usefixtures("specs_catalog")
def test_search_spec_filters_combine_with_and(db_session: Session) -> None:
    names = _names(
        db_session,
        spec_filters=[_spec("gpu_rank", "gte", 40), _spec("ram_gb", "gte", 32)],
    )

    assert names == ["Mock B"]


def test_search_spec_filter_string_equality_and_list_operators(db_session: Session) -> None:
    wired = _add(
        db_session,
        canonical_name="Mock Wired",
        category=Category.mouse,
        specs={"connection": ["wired"], "shape": "ambidextrous"},
    )
    both = _add(
        db_session,
        canonical_name="Mock Both",
        category=Category.mouse,
        specs={"connection": ["wired", "bluetooth"], "shape": "ergo_right"},
    )
    radio = _add(
        db_session,
        canonical_name="Mock Radio",
        category=Category.mouse,
        specs={"connection": ["wireless_2_4"]},
    )
    for product in (wired, both, radio):
        _offer(db_session, product)

    def names(spec_filter: SpecFilter) -> set[str]:
        return set(_names(db_session, category="mouse", spec_filters=[spec_filter]))

    assert names(_spec("connection", "contains", "bluetooth")) == {"Mock Both"}
    assert names(_spec("connection", "contains", "wired")) == {"Mock Wired", "Mock Both"}
    assert names(_spec("connection", "contains_any", ["bluetooth", "wireless_2_4"])) == {
        "Mock Both",
        "Mock Radio",
    }
    assert names(_spec("connection", "contains_any", [])) == set()
    assert names(_spec("shape", "eq", "ergo_right")) == {"Mock Both"}
    assert names(_spec("shape", "in", ["ergo_right", "ambidextrous"])) == {
        "Mock Wired",
        "Mock Both",
    }


def test_search_spec_field_name_is_a_bound_parameter(db_session: Session) -> None:
    product = _add(db_session, specs={"ram_gb": 16})
    _offer(db_session, product)

    names = _names(db_session, spec_filters=[_spec("ram_gb') OR ('1'='1", "gte", 0)])

    assert names == []


def test_product_query_rejects_out_of_range_paging_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProductQuery(limit=0)
    with pytest.raises(ValidationError):
        ProductQuery(offset=-1)
    with pytest.raises(ValidationError):
        ProductQuery.model_validate({"sort": "relevance"})
    with pytest.raises(ValidationError):
        ProductQuery.model_validate({"keywords": ["x"]})


def test_search_in_with_empty_list_matches_nothing_and_price_bounds_combine(
    db_session: Session,
) -> None:
    product = _add(db_session, canonical_name="Mock Range", specs={"ram_gb": 16})
    _offer(db_session, product, url="https://m.example/lo", price=10_000_000)
    _offer(db_session, product, url="https://m.example/mid", price=20_000_000)
    _offer(db_session, product, url="https://m.example/hi", price=30_000_000)

    assert _names(db_session, spec_filters=[_spec("ram_gb", "in", [])]) == []
    page = ProductRepository(db_session).search(
        ProductQuery(price_min=15_000_000, price_max=25_000_000)
    )
    assert [(h.min_price, h.max_price, h.offers_count) for h in page.items] == [
        (20_000_000, 20_000_000, 1)
    ]
