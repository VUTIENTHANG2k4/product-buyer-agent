"""T6.2: CatalogService trên PostgreSQL thật."""

from datetime import timedelta

import pytest
from sqlmodel import Session

from app.domain.catalog import CatalogFilters
from app.domain.dto import SpecFilter
from app.domain.enums import Category, PriceType, SiteKey, StockStatus
from app.domain.errors import ProductNotFound, ValidationFailed
from app.services.catalog_service import CatalogService
from scripts.seed import seed_database
from tests.factories import make_price_history
from tests.service_support import NOW, add_offer, add_product, clock


def service(session: Session) -> CatalogService:
    return CatalogService(session, now=clock)


def test_search_returns_cheapest_offer_and_price_range_across_sites(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, site=SiteKey.gearvn, price=28_000_000)
    add_offer(db_session, product, site=SiteKey.fptshop, price=26_000_000)
    add_offer(db_session, product, site=SiteKey.anphat, price=27_000_000)

    result = service(db_session).search(CatalogFilters())

    (item,) = result.items
    assert (result.total, item.min_price, item.max_price, item.offers_count) == (
        1,
        26_000_000,
        28_000_000,
        3,
    )
    assert item.best_offer.site is SiteKey.fptshop
    assert item.best_offer.url.startswith("https://mock.example/")
    assert item.name == product.canonical_name


def test_spec_filters_use_json_specs(db_session: Session) -> None:
    strong = add_product(db_session, specs={"gpu_rank": 50, "ram_gb": 32})
    weak = add_product(db_session, specs={"gpu_rank": 20, "ram_gb": 16})
    for product in (strong, weak):
        add_offer(db_session, product)

    filters = CatalogFilters(
        spec_filters=[
            SpecFilter(field="gpu_rank", op="gte", value=40),
            SpecFilter(field="ram_gb", op="gte", value=16),
        ]
    )
    result = service(db_session).search(filters)

    assert [item.product_id for item in result.items] == [strong.id]


def test_price_filter_uses_effective_price_so_member_price_compares_by_list_price(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    add_offer(
        db_session, product, price=20_000_000, list_price=30_000_000, price_type=PriceType.member
    )

    cheap = service(db_session).search(CatalogFilters(price_max=25_000_000))
    pricey = service(db_session).search(CatalogFilters(price_max=30_000_000))

    assert cheap.items == []
    (item,) = pricey.items
    assert (item.min_price, item.best_offer.price, item.best_offer.effective_price) == (
        30_000_000,
        20_000_000,
        30_000_000,
    )


def test_sites_filter_limits_best_offer_and_counts_to_those_sites(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, site=SiteKey.gearvn, price=30_000_000)
    add_offer(db_session, product, site=SiteKey.fptshop, price=25_000_000)

    (item,) = service(db_session).search(CatalogFilters(sites=[SiteKey.gearvn])).items

    assert (item.best_offer.site, item.min_price, item.offers_count) == (
        SiteKey.gearvn,
        30_000_000,
        1,
    )


def test_out_of_stock_offers_are_ignored_unless_requested(db_session: Session) -> None:
    mixed = add_product(db_session)
    add_offer(db_session, mixed, price=20_000_000, stock_status=StockStatus.out_of_stock)
    add_offer(db_session, mixed, price=25_000_000, stock_status=StockStatus.in_stock)
    gone = add_product(db_session)
    add_offer(db_session, gone, price=10_000_000, stock_status=StockStatus.out_of_stock)

    default = service(db_session).search(CatalogFilters())
    with_oos = service(db_session).search(CatalogFilters(include_out_of_stock=True))

    assert [(i.product_id, i.min_price, i.in_stock) for i in default.items] == [
        (mixed.id, 25_000_000, True)
    ]
    assert [(i.product_id, i.min_price, i.in_stock) for i in with_oos.items] == [
        (gone.id, 10_000_000, False),
        (mixed.id, 20_000_000, False),
    ]


@pytest.mark.parametrize(
    ("age_hours", "stale"), [(0, False), (23, False), (24, False), (25, True), (72, True)]
)
def test_stale_when_oldest_shown_price_is_older_than_24_hours(
    db_session: Session, age_hours: int, stale: bool
) -> None:
    add_offer(db_session, add_product(db_session), scraped_at=NOW - timedelta(hours=age_hours))

    result = service(db_session).search(CatalogFilters())

    assert result.stale is stale
    assert result.data_as_of == NOW - timedelta(hours=age_hours)


def test_data_as_of_is_the_oldest_best_offer_and_empty_result_is_not_stale(
    db_session: Session,
) -> None:
    add_offer(db_session, add_product(db_session), scraped_at=NOW - timedelta(hours=1))
    add_offer(db_session, add_product(db_session), scraped_at=NOW - timedelta(hours=30))

    result = service(db_session).search(CatalogFilters())
    empty = service(db_session).search(CatalogFilters(category=Category.mouse))

    assert (result.data_as_of, result.stale) == (NOW - timedelta(hours=30), True)
    assert (empty.items, empty.data_as_of, empty.stale, empty.total) == ([], None, False, 0)


def test_text_query_matches_every_word_and_treats_wildcards_literally(
    db_session: Session,
) -> None:
    target = add_product(db_session, brand="ASUS", canonical_name="ASUS TUF Gaming F15")
    other = add_product(db_session, brand="Acer", canonical_name="Acer Nitro 5")
    for product in (target, other):
        add_offer(db_session, product)

    def ids(q: str) -> list[int | None]:
        return [i.product_id for i in service(db_session).search(CatalogFilters(q=q)).items]

    assert ids("asus f15") == [target.id]
    assert ids("tuf nitro") == []
    assert ids("%") == []
    assert ids("a_us") == []


def test_sort_orders_and_relevance_means_cheapest_first(db_session: Session) -> None:
    cheap, mid, dear = (add_product(db_session) for _ in range(3))
    for product, price in ((dear, 30_000_000), (cheap, 10_000_000), (mid, 20_000_000)):
        add_offer(db_session, product, price=price)

    def order(sort: str) -> list[int | None]:
        filters = CatalogFilters(sort=sort)  # type: ignore[arg-type]
        return [i.product_id for i in service(db_session).search(filters).items]

    assert order("relevance") == order("price_asc") == [cheap.id, mid.id, dear.id]
    assert order("price_desc") == [dear.id, mid.id, cheap.id]


def test_limit_and_offset_page_through_results(db_session: Session) -> None:
    for price in (10, 20, 30):
        add_offer(db_session, add_product(db_session), price=price * 1_000_000)

    page = service(db_session).search(CatalogFilters(limit=1, offset=1))

    assert (page.total, [i.min_price for i in page.items]) == (3, [20_000_000])


def test_key_specs_keep_at_most_six_fields_and_skip_missing_values(db_session: Session) -> None:
    specs = {
        "cpu_model": "i7",
        "gpu_model": None,
        "ram_gb": 16,
        "storage_gb": 512,
        "screen_in": 15.6,
        "refresh_hz": 144,
        "panel": "IPS",
        "os": "Win 11",
    }
    add_offer(db_session, add_product(db_session, specs=specs))

    (item,) = service(db_session).search(CatalogFilters()).items

    assert list(item.key_specs) == ["cpu_model", "ram_gb", "storage_gb", "screen_in", "refresh_hz"]


def test_applied_filters_list_only_what_was_set(db_session: Session) -> None:
    filters = CatalogFilters(
        category=Category.laptop,
        price_max=30_000_000,
        sites=[SiteKey.gearvn],
        spec_filters=[SpecFilter(field="gpu_rank", op="gte", value=40)],
        limit=5,
    )

    applied = service(db_session).search(filters).applied_filters

    assert applied == {
        "category": "laptop",
        "price_max": 30_000_000,
        "sites": ["gearvn"],
        "spec_filters": [{"field": "gpu_rank", "op": "gte", "value": 40}],
        "sort": "relevance",
        "limit": 5,
    }


def test_clock_without_timezone_is_rejected(db_session: Session) -> None:
    naive = CatalogService(db_session, now=lambda: NOW.replace(tzinfo=None))
    with pytest.raises(ValidationFailed, match="múi giờ"):
        naive.search(CatalogFilters())


def test_seed_laptops_with_rtx_4060_or_better_under_30_million(db_session: Session) -> None:
    seed_database(db_session, "dev", now=NOW)
    catalog = service(db_session)
    filters = CatalogFilters(
        category=Category.laptop,
        price_max=30_000_000,
        spec_filters=[SpecFilter(field="gpu_rank", op="gte", value=40)],
        limit=20,
    )

    result = catalog.search(filters)

    assert result.total >= 3
    assert not result.stale
    for item in result.items:
        assert item.min_price <= 30_000_000
        assert catalog.get_detail(item.product_id).specs["gpu_rank"] >= 40


# ---- chi tiết ----
def test_detail_lists_all_offers_but_price_range_ignores_out_of_stock(db_session: Session) -> None:
    product = add_product(db_session, specs={"ram_gb": 16})
    add_offer(db_session, product, price=20_000_000, stock_status=StockStatus.out_of_stock)
    add_offer(db_session, product, price=25_000_000)
    add_offer(db_session, product, price=22_000_000, is_active=False)

    detail = service(db_session).get_detail(product.id or 0)

    assert [o.price for o in detail.offers] == [20_000_000, 25_000_000]
    assert (detail.min_price, detail.max_price) == (25_000_000, 25_000_000)
    assert detail.specs == {"ram_gb": 16}


def test_detail_of_product_without_offers_has_no_prices(db_session: Session) -> None:
    detail = service(db_session).get_detail(add_product(db_session).id or 0)
    assert (detail.offers, detail.min_price, detail.max_price) == ([], None, None)


def test_unknown_product_detail_raises_product_not_found(db_session: Session) -> None:
    with pytest.raises(ProductNotFound) as caught:
        service(db_session).get_detail(999_999)
    assert caught.value.details == {"product_id": 999_999}


def test_get_many_keeps_requested_order_and_skips_unknown_ids(db_session: Session) -> None:
    first, second = add_product(db_session), add_product(db_session)
    assert first.id and second.id

    found = service(db_session).get_many([second.id, 999_999, first.id])

    assert [p.product_id for p in found] == [second.id, first.id]


# ---- lịch sử giá ----
def _history(db_session: Session, offer_id: int, price: int, days_ago: int) -> None:
    db_session.add(
        make_price_history(offer_id, price=price, scraped_at=NOW - timedelta(days=days_ago))
    )
    db_session.flush()


def test_price_history_groups_points_by_site_within_the_window(db_session: Session) -> None:
    product = add_product(db_session)
    gear = add_offer(db_session, product, site=SiteKey.gearvn)
    fpt = add_offer(db_session, product, site=SiteKey.fptshop)
    assert gear.id and fpt.id
    _history(db_session, gear.id, 30_000_000, 40)  # ngoài cửa sổ 30 ngày
    _history(db_session, gear.id, 28_000_000, 10)
    _history(db_session, gear.id, 27_000_000, 1)
    _history(db_session, fpt.id, 26_500_000, 5)

    result = service(db_session).price_history(product.id or 0, days=30)

    assert [(s.site, [p.price for p in s.points]) for s in result.series] == [
        (SiteKey.fptshop, [26_500_000]),
        (SiteKey.gearvn, [28_000_000, 27_000_000]),
    ]
    assert (result.min_price, result.max_price) == (26_500_000, 28_000_000)


def test_price_history_without_points_is_empty(db_session: Session) -> None:
    result = service(db_session).price_history(add_product(db_session).id or 0)
    assert (result.series, result.min_price, result.max_price) == ([], None, None)


@pytest.mark.parametrize("days", [0, -1, 181])
def test_price_history_rejects_days_outside_1_to_180(db_session: Session, days: int) -> None:
    with pytest.raises(ValidationFailed):
        service(db_session).price_history(add_product(db_session).id or 0, days=days)


def test_price_history_of_unknown_product_raises(db_session: Session) -> None:
    with pytest.raises(ProductNotFound):
        service(db_session).price_history(999_999)
