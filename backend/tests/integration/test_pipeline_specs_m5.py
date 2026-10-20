"""Thông số trích bằng luật được lưu vào Product qua resolver tạm thời (T5.1)."""

from pathlib import Path

import pytest
from sqlmodel import Session

from app.db.models import Product
from app.db.repositories import OfferRepository, OfferUpsert, ProductQuery, ProductRepository
from app.domain.dto import ListingItem, ProductDetail, SpecFilter
from app.domain.enums import Category, SiteKey
from app.scrapers.pipeline import resolve_product_interim
from app.scrapers.sites.mockshop import MockShopScraper
from scripts.save_mockshop_fixtures import FIXTURE_DIR

URL = "http://localhost:8100/p/asus-mock-strix-15-x01-mk-la001"
DETAIL_FIXTURE = "detail_asus-mock-strix-15-x01-mk-la001.html"


def listing_item(**raw_specs: str) -> ListingItem:
    return ListingItem(
        site=SiteKey.mockshop,
        url=URL,
        title="Laptop ASUS Mock Strix 15 X01",
        price=15_750_000,
        raw_specs=raw_specs,
        category_hint=Category.laptop,
    )


def mock_detail() -> ProductDetail:
    html = Path(FIXTURE_DIR, DETAIL_FIXTURE).read_text(encoding="utf-8")
    return MockShopScraper(None).parse_detail(html, URL)  # type: ignore[arg-type]


def get_product(session: Session, product_id: int) -> Product:
    product = ProductRepository(session).get(product_id)
    assert product is not None
    return product


def test_new_product_gets_specs_from_the_detail_page(db_session: Session) -> None:
    detail = mock_detail()
    assert "Card đồ họa" in detail.raw_specs

    product_id = resolve_product_interim(db_session, Category.laptop, listing_item(), detail)

    product = get_product(db_session, product_id)
    assert product.specs["gpu_model"] == "RTX 4050"
    assert product.specs["gpu_rank"] == 30
    assert product.specs["ram_gb"] == 8
    assert product.specs["storage_gb"] == 512
    assert product.specs["cpu_model"] == "i5-13500H"
    assert product.specs_confidence == 1.0


def test_specs_are_queryable_by_the_catalog_filters(db_session: Session) -> None:
    product_id = resolve_product_interim(db_session, Category.laptop, listing_item(), mock_detail())
    OfferRepository(db_session).upsert(
        OfferUpsert(
            product_id=product_id,
            site=SiteKey.mockshop,
            url=URL,
            title="Laptop ASUS Mock Strix 15 X01",
            price=15_750_000,
        )
    )

    def hits(*filters: SpecFilter) -> list[int | None]:
        page = ProductRepository(db_session).search(
            ProductQuery(category=Category.laptop, spec_filters=list(filters))
        )
        return [hit.product.id for hit in page.items]

    assert hits(SpecFilter(field="gpu_rank", op="gte", value=30)) == [product_id]
    assert hits(SpecFilter(field="ram_gb", op="gte", value=8)) == [product_id]
    assert hits(SpecFilter(field="gpu_rank", op="gte", value=40)) == []
    assert hits(SpecFilter(field="is_gaming", op="eq", value=True)) == [product_id]


def test_product_with_missing_required_field_has_low_confidence(db_session: Session) -> None:
    item = listing_item(CPU="Intel Core i5-13500H", RAM="8GB DDR5")

    product_id = resolve_product_interim(db_session, Category.laptop, item, None)

    product = get_product(db_session, product_id)
    assert "gpu_model" not in product.specs and "storage_gb" not in product.specs
    assert product.specs_confidence == pytest.approx(0.24)


def test_existing_offer_fills_missing_specs_without_overwriting_known_ones(
    db_session: Session,
) -> None:
    first = listing_item(CPU="Intel Core i5-13500H", RAM="8GB DDR5")
    product_id = resolve_product_interim(db_session, Category.laptop, first, None)
    OfferRepository(db_session).upsert(
        OfferUpsert(
            product_id=product_id,
            site=SiteKey.mockshop,
            url=URL,
            title=first.title,
            price=15_750_000,
        )
    )
    before = get_product(db_session, product_id)
    assert before.specs_confidence < 0.5

    # Lượt sau có trang chi tiết (RAM ghi khác để kiểm giá trị cũ không bị ghi đè).
    detail = mock_detail().model_copy(
        update={"raw_specs": {**mock_detail().raw_specs, "RAM": "16GB DDR5"}}
    )
    again = resolve_product_interim(db_session, Category.laptop, first, detail)

    assert again == product_id
    after = get_product(db_session, product_id)
    assert after.specs["ram_gb"] == 8  # giá trị đã có được giữ
    assert after.specs["gpu_model"] == "RTX 4050"  # trường thiếu được điền
    assert after.specs["gpu_rank"] == 30
    assert after.specs_confidence == 1.0


def test_category_without_extractor_keeps_empty_specs(db_session: Session) -> None:
    item = ListingItem(
        site=SiteKey.mockshop,
        url="http://localhost:8100/p/phone-mock",
        title="Điện thoại Mock X 256GB",
        price=9_990_000,
    )

    product_id = resolve_product_interim(db_session, Category.phone, item, None)

    product = get_product(db_session, product_id)
    assert (product.specs, product.specs_confidence) == ({}, 0.0)
