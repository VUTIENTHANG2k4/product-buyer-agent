"""Profile `e2e` của seed: tập con đủ cho các luồng chính, không có dữ liệu phụ (docs/09 §3).

Tách khỏi `test_seed_data.py` vì module đó giữ một transaction seed `eval` suốt module.
"""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session, func, select

from app.db.models import Product, ShoppingList
from app.db.repositories import ProductQuery, ProductRepository
from app.domain.dto import SpecFilter
from app.domain.enums import Category
from scripts.seed import FIXTURE_DIR, load_catalog, seed_database

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class TestE2eProfile:
    @pytest.fixture
    def e2e(self, db_session: Session) -> Session:
        seed_database(db_session, "e2e", now=NOW)
        return db_session

    def test_is_a_small_subset_of_the_full_catalog(self, e2e: Session) -> None:
        total = e2e.exec(select(func.count()).select_from(Product)).one()

        assert 10 <= total < len(load_catalog(FIXTURE_DIR))

    def test_supports_the_main_flow_search_compare_list_and_alert(self, e2e: Session) -> None:
        query = ProductQuery(
            category=Category.laptop,
            price_max=30_000_000,
            spec_filters=[SpecFilter(field="gpu_rank", op="gte", value=40)],
            limit=100,
        )

        page = ProductRepository(e2e).search(query)

        assert page.total >= 3
        assert any(hit.offers_count >= 2 for hit in page.items)

    def test_has_every_accessory_group_for_the_search_flow(self, e2e: Session) -> None:
        categories = set(e2e.exec(select(Product.category)).all())

        assert {Category.laptop, Category.mouse, Category.keyboard, Category.headset} <= categories

    def test_starts_without_lists_so_the_e2e_flow_creates_its_own(self, e2e: Session) -> None:
        assert e2e.exec(select(func.count()).select_from(ShoppingList)).one() == 0
