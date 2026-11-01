"""T9.3: `parse_detail` đọc giá từ trang chi tiết (dùng để làm mới giá offer đang theo dõi)."""

from pathlib import Path
from typing import Any

import pytest

from app.domain.enums import PriceType, StockStatus
from app.scrapers.parsing import schema_offer, schema_price, schema_stock
from app.scrapers.sites.anphat import AnPhatScraper
from app.scrapers.sites.fptshop import FptShopScraper
from app.scrapers.sites.gearvn import GearVNScraper, _strikethrough_price
from app.scrapers.sites.mockshop import MockShopScraper
from tests.fakes import FakeFetcher
from tests.unit.test_mockshop_scraper import detail_fixture, fixture

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def html(site: str, name: str) -> str:
    return (FIXTURES / site / name).read_text(encoding="utf-8")


def parse(scraper_type: Any, site: str, name: str) -> Any:
    scraper = scraper_type(FakeFetcher({}))
    return scraper.parse_detail(html(site, name), f"https://detail.example/{name}")


# ---- GearVN: JSON-LD offers + priceSpecification gạch ngang ----
def test_gearvn_detail_reads_price_struck_price_and_stock() -> None:
    detail = parse(GearVNScraper, "gearvn", "detail_laptop-acer-aspire-lite-15-al15-53p-56qh.html")

    assert (detail.price, detail.list_price) == (19_990_000, 24_990_000)
    assert (detail.price_type, detail.stock_status) == (PriceType.sale, StockStatus.in_stock)


def test_gearvn_detail_without_a_struck_price_is_regular() -> None:
    page = html("gearvn", "detail_laptop-acer-aspire-lite-15-al15-53p-56qh.html")
    page = page.replace("StrikethroughPrice", "ListPrice")

    detail = GearVNScraper(FakeFetcher({})).parse_detail(page, "https://gearvn.com/products/x")

    assert (detail.price, detail.list_price, detail.price_type) == (
        19_990_000,
        None,
        PriceType.regular,
    )


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"priceType": "https://schema.org/StrikethroughPrice", "price": 24_990_000}, 24_990_000),
        ({"priceType": "https://schema.org/StrikethroughPrice", "price": 100}, None),  # ≤ giá bán
        ({"priceType": "https://schema.org/StrikethroughPrice", "price": 19_990_000}, None),
        ({"priceType": "https://schema.org/ListPrice", "price": 24_990_000}, None),
        ({"price": 24_990_000}, None),
        ("not a dict", None),
    ],
)
def test_gearvn_strikethrough_price_needs_a_higher_struck_price(spec: Any, expected: Any) -> None:
    assert _strikethrough_price({"priceSpecification": spec}, 19_990_000) == expected
    assert _strikethrough_price({"priceSpecification": [spec]}, 19_990_000) == expected


def test_gearvn_detail_without_json_ld_has_no_price() -> None:
    detail = GearVNScraper(FakeFetcher({})).parse_detail(
        "<html></html>", "https://gearvn.com/products/x"
    )

    assert (detail.price, detail.price_type, detail.stock_status) == (
        None,
        PriceType.unknown,
        StockStatus.unknown,
    )


# ---- An Phát: chỉ giá bán, loại giá/tồn kho để unknown ----
@pytest.mark.parametrize(
    ("name", "price"),
    [
        ("detail_laptop-hp-victus-15-fa2452tx-d44vlpa.html", 27_690_000),
        ("detail_chuot-logitech-g102-lightsync.html", 389_000),
        ("detail_ban-phim-co-aula-f75-grey-white-milk-white-switch.html", 1_149_000),
        ("detail_tai-nghe-logitech-g-pro-x3-lightspeed-magenta.html", 5_490_000),
    ],
)
def test_anphat_detail_reads_only_the_selling_price(name: str, price: int) -> None:
    detail = parse(AnPhatScraper, "anphat", name)

    assert detail.price == price
    assert (detail.list_price, detail.price_type, detail.stock_status) == (
        None,
        PriceType.unknown,
        StockStatus.unknown,
    )


# ---- FPT Shop: dùng chung logic với trang sản phẩm ----
@pytest.mark.parametrize(
    ("name", "price", "list_price", "price_type"),
    [
        ("detail_chuot-khong-day-elecom-m-ir07dr.html", 299_000, 319_000, PriceType.sale),
        ("detail_ban-phim-co-khong-day-mchose-g75-pro-v2.html", 1_690_000, None, PriceType.regular),
        ("detail_tai-nghe-corsair-hs50-pro-stereo.html", 1_290_000, 1_390_000, PriceType.sale),
    ],
)
def test_fptshop_detail_reads_price_and_struck_price(
    name: str, price: int, list_price: int | None, price_type: PriceType
) -> None:
    detail = parse(FptShopScraper, "fptshop", name)

    assert (detail.price, detail.list_price, detail.price_type) == (price, list_price, price_type)
    assert detail.stock_status is StockStatus.in_stock


def test_fptshop_detail_price_matches_the_product_item_price() -> None:
    name = "detail_laptop-asus-tuf-gaming-16-fx610jh-tu008w-i5-14450hx.html"
    scraper = FptShopScraper(FakeFetcher({}))
    url = f"https://fptshop.com.vn/{name}"
    item = scraper.parse_product(html("fptshop", name), url, category=scraper_category())
    detail = scraper.parse_detail(html("fptshop", name), url)

    assert (detail.price, detail.list_price, detail.price_type, detail.stock_status) == (
        item.price,
        item.list_price,
        item.price_type,
        item.stock_status,
    )


def scraper_category() -> Any:
    from app.domain.enums import Category

    return Category.laptop


# ---- mock-shop ----
def test_mockshop_detail_reads_price_and_stock_but_keeps_price_type_unknown() -> None:
    detail = MockShopScraper(FakeFetcher({})).parse_detail(
        fixture(detail_fixture(priced=True)[0]), "http://localhost:8100/p/x"
    )

    assert detail.price == 15_750_000
    assert (detail.price_type, detail.stock_status) == (PriceType.unknown, StockStatus.in_stock)


def test_mockshop_detail_with_a_masked_price_has_no_price() -> None:
    detail = MockShopScraper(FakeFetcher({})).parse_detail(
        fixture(detail_fixture(priced=False)[0]), "http://localhost:8100/p/x"
    )

    assert detail.price is None


# ---- hàm dùng chung ----
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (27_490_000, 27_490_000),
        ("27490000", 27_490_000),
        (27_490_000.0, 27_490_000),
        (27_490_000.5, None),
        (True, None),
        (None, None),
        ("Liên hệ", None),
        (5, None),  # dưới 10.000 ₫
        ([1], None),
    ],
)
def test_schema_price_accepts_numbers_and_numeric_strings_in_range(
    value: object, expected: int | None
) -> None:
    assert schema_price(value) == expected


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        ("https://schema.org/InStock", StockStatus.in_stock),
        ("http://schema.org/OutOfStock", StockStatus.out_of_stock),
        ("https://schema.org/PreOrder", StockStatus.preorder),
        ("SoldOut", StockStatus.out_of_stock),
        ("https://schema.org/Whatever", StockStatus.unknown),
        (None, StockStatus.unknown),
        (3, StockStatus.unknown),
    ],
)
def test_schema_stock_maps_availability(availability: object, expected: StockStatus) -> None:
    assert schema_stock({"availability": availability}) == expected


def test_schema_offer_takes_the_first_dict_of_a_list_and_tolerates_junk() -> None:
    assert schema_offer({"offers": [1, {"price": 5}, {"price": 6}]}) == {"price": 5}
    assert schema_offer({"offers": {"price": 7}}) == {"price": 7}
    assert schema_offer({"offers": "x"}) == {}
    assert schema_offer({}) == {}
