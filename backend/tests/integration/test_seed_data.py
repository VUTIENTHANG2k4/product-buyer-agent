"""Dữ liệu seed thật (tests/fixtures/seed) phải phủ đủ docs/eval/queries.yaml (docs/09 §3).

Test dịch `constraints` của từng câu eval thành `ProductQuery` rồi chạy `ProductRepository.search`
trên DB đã seed: đây là xấp xỉ việc agent lọc (không thay `make eval`), đủ để biết mỗi câu có đáp
án xác định trong dữ liệu hư cấu.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine
from sqlmodel import Session, col, func, select

from app.db.models import Offer, PriceAlert, PriceHistory, Product, ShoppingListItem
from app.db.repositories import ProductQuery, ProductRepository
from app.domain.dto import SpecFilter
from app.domain.enums import Category, SiteKey
from scripts.seed import FIXTURE_DIR, load_catalog, seed_database

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
QUERIES_FILE = Path(__file__).resolve().parents[3] / "docs" / "eval" / "queries.yaml"

# Câu eval mà ràng buộc không nằm hết trong `constraints` (L09 hỏi RTX 4090 = gpu_rank ≥ 80).
EXTRA_SPEC_FILTERS = {"L09": [SpecFilter(field="gpu_rank", op="gte", value=80)]}
# Câu "rẻ nhất": kết quả đầu phải duy nhất, không hòa giá.
CHEAPEST_CASES = ("L03", "A07", "S02")
# Câu hội thoại dựa vào kết quả của một câu tìm kiếm trước đó: (câu nguồn, số kết quả tối thiểu để
# "máy thứ N" có nghĩa).
CONTEXT_SOURCE = {
    "C01": ("L01", 2),
    "C02": ("L01", 2),
    "C03": ("L01", 1),
    "C04": ("A01", 1),
    "C06": ("A03", 3),
}


def load_cases() -> list[dict[str, Any]]:
    data = yaml.safe_load(QUERIES_FILE.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = data["cases"]
    return cases


CASES = load_cases()
CASES_BY_ID = {case["id"]: case for case in CASES}
SEARCH_CASES = [
    case
    for case in CASES
    if not case.get("expect_clarification")
    and (case.get("expected", {}).get("constraints") or case["id"] in EXTRA_SPEC_FILTERS)
]


def build_query(case: dict[str, Any], **overrides: Any) -> ProductQuery:
    """Dịch intent + constraints của một câu eval thành điều kiện tìm kiếm."""
    expected = case["expected"]
    intent = expected.get("intent", {})
    fields: dict[str, Any] = {
        "category": intent.get("category"),
        "price_max": intent.get("price_max"),
        "sites": intent.get("sites", []),
        "spec_filters": list(EXTRA_SPEC_FILTERS.get(case["id"], [])),
        "brands": [],
        "limit": 100,
        "sort": intent.get("sort", "price_asc"),
    }
    for constraint in expected.get("constraints", []):
        field, op, value = constraint["field"], constraint["op"], constraint["value"]
        if field == "min_price":
            fields["price_max" if op == "lte" else "price_min"] = value
        elif field == "brand":
            fields["brands"] = value if op == "in" else [value]
        elif field == "site":
            fields["sites"] = value
        elif field.startswith("spec."):
            fields["spec_filters"].append(SpecFilter(field=field[5:], op=op, value=value))
        else:  # pragma: no cover - khóa mới trong queries.yaml cần được dịch ở đây
            raise AssertionError(f"{case['id']}: chưa dịch được ràng buộc {field}")
    fields.update(overrides)
    return ProductQuery(**fields)


@pytest.fixture(scope="module")
def seeded(db_engine: Engine) -> Iterator[Session]:
    """Seed `eval` một lần cho cả module (seed mất vài giây); mọi test ở đây chỉ đọc.

    Transaction riêng bị rollback khi hết module. Test dùng `db_session` (cũng seed cùng khóa) phải
    nằm ở module khác, nếu không sẽ chờ khóa unique của transaction này.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        seed_database(session, "eval", now=NOW)
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


class TestCatalogSize:
    def test_has_at_least_30_laptops_and_10_per_accessory_group(self, seeded: Session) -> None:
        counts = dict(
            seeded.exec(
                select(Product.category, func.count()).group_by(col(Product.category))
            ).all()
        )

        assert counts[Category.laptop] >= 30
        for category in (Category.mouse, Category.keyboard, Category.headset):
            assert counts[category] >= 10, category

    def test_every_product_and_offer_is_fictional(self, seeded: Session) -> None:
        names = seeded.exec(select(Product.canonical_name)).all()
        offers = seeded.exec(select(Offer.title, Offer.url)).all()

        assert names and all("Mock" in name for name in names)
        assert all("Mock" in title and ".example/" in url for title, url in offers)

    def test_seed_files_cover_every_tier_one_category(self) -> None:
        catalog = load_catalog(FIXTURE_DIR)

        assert {item.category for item in catalog} == {
            Category.laptop,
            Category.mouse,
            Category.keyboard,
            Category.headset,
        }


class TestEvalCoverage:
    @pytest.mark.parametrize("case", SEARCH_CASES, ids=lambda case: case["id"])
    def test_case_has_the_expected_number_of_answers(
        self, seeded: Session, case: dict[str, Any]
    ) -> None:
        expected_min = case["expected"].get("min_results", 1)
        page = ProductRepository(seeded).search(build_query(case))

        if expected_min == 0:
            assert page.total == 0, f"{case['id']}: seed phải KHÔNG có kết quả"
        else:
            assert page.total >= expected_min, f"{case['id']}: chỉ có {page.total} kết quả"

    def test_l09_has_no_answer_only_because_of_price_not_because_the_rank_is_missing(
        self, seeded: Session
    ) -> None:
        case = CASES_BY_ID["L09"]

        without_price_cap = ProductRepository(seeded).search(build_query(case, price_max=None))

        assert without_price_cap.total >= 1

    @pytest.mark.parametrize("case_id", CHEAPEST_CASES)
    def test_cheapest_answer_is_unique(self, seeded: Session, case_id: str) -> None:
        case = CASES_BY_ID[case_id]
        query = build_query(case, sort="price_asc")
        if case_id == "S02":  # câu chỉ có intent, không có constraints
            query = ProductQuery(category=Category.laptop, sites=[SiteKey.gearvn], limit=100)

        hits = ProductRepository(seeded).search(query).items

        assert len(hits) >= 2
        assert hits[0].min_price < hits[1].min_price

    @pytest.mark.parametrize("case_id", sorted(CONTEXT_SOURCE))
    def test_followup_case_has_enough_results_from_its_source_query(
        self, seeded: Session, case_id: str
    ) -> None:
        source_id, minimum = CONTEXT_SOURCE[case_id]

        page = ProductRepository(seeded).search(build_query(CASES_BY_ID[source_id]))

        assert page.total >= minimum, f"{case_id}: {source_id} chỉ có {page.total} kết quả"

    @pytest.mark.parametrize("case_id", sorted(CONTEXT_SOURCE))
    def test_followup_positions_are_not_decided_by_a_price_tie(
        self, seeded: Session, case_id: str
    ) -> None:
        """ "Máy thứ N" cần N vị trí đầu (và vị trí kế tiếp) có giá khác nhau từng đôi một."""
        source_id, minimum = CONTEXT_SOURCE[case_id]
        hits = ProductRepository(seeded).search(build_query(CASES_BY_ID[source_id])).items

        prices = [hit.min_price for hit in hits[: minimum + 1]]

        assert len(prices) == len(set(prices)), f"{case_id}: giá trùng trong {prices}"

    def test_l03_has_a_unique_cheapest_answer_even_when_restricted_to_gaming_laptops(
        self, seeded: Session
    ) -> None:
        gaming = SpecFilter(field="is_gaming", op="eq", value=True)
        case = CASES_BY_ID["L03"]
        query = build_query(case, spec_filters=[*build_query(case).spec_filters, gaming])

        hits = ProductRepository(seeded).search(query).items

        assert len(hits) >= 2
        assert hits[0].min_price < hits[1].min_price

    def test_every_case_with_context_has_a_declared_source_query(self) -> None:
        with_context = {case["id"] for case in CASES if case.get("context")}

        assert with_context == set(CONTEXT_SOURCE)


class TestOffersAndHistory:
    def test_many_laptops_are_sold_on_two_or_three_sites(self, seeded: Session) -> None:
        sites_per_product = seeded.exec(
            select(Offer.product_id, func.count(func.distinct(Offer.site)))
            .join(Product, col(Product.id) == col(Offer.product_id))
            .where(col(Product.category) == Category.laptop)
            .group_by(col(Offer.product_id))
        ).all()

        counts = [count for _, count in sites_per_product]
        assert sum(1 for count in counts if count >= 2) >= 10
        assert max(counts) == 3

    def test_at_least_ten_products_have_a_30_day_history_with_several_points(
        self, seeded: Session
    ) -> None:
        rows = seeded.exec(
            select(
                Offer.product_id,
                Offer.id,
                func.count(col(PriceHistory.id)),
                func.min(col(PriceHistory.scraped_at)),
            )
            .join(PriceHistory, col(PriceHistory.offer_id) == col(Offer.id))
            .group_by(col(Offer.product_id), col(Offer.id))
        ).all()

        rich = {product_id for product_id, _, points, _ in rows if points >= 4}
        assert len(rich) >= 10
        assert all(29 <= (NOW - first).days <= 30 for *_, first in rows)

    def test_every_offer_has_history_from_30_days_ago_up_to_now(self, seeded: Session) -> None:
        spans = seeded.exec(
            select(
                func.count(col(PriceHistory.id)),
                func.min(col(PriceHistory.scraped_at)),
                func.max(col(PriceHistory.scraped_at)),
            )
            .join(Offer, col(PriceHistory.offer_id) == col(Offer.id))
            .group_by(col(Offer.id))
        ).all()
        offers = seeded.exec(select(func.count()).select_from(Offer)).one()

        assert len(spans) == offers
        for rows, first, last in spans:
            assert rows >= 2
            assert (NOW - first).days == 30
            assert last == NOW

    def test_some_offers_got_cheaper_and_some_got_dearer_over_the_30_days(
        self, seeded: Session
    ) -> None:
        rows = seeded.exec(
            select(col(PriceHistory.offer_id), col(PriceHistory.price)).order_by(
                col(PriceHistory.offer_id), col(PriceHistory.scraped_at), col(PriceHistory.id)
            )
        ).all()
        series: dict[int, list[int]] = {}
        for offer_id, price in rows:
            series.setdefault(offer_id, []).append(price)

        cheaper = sum(1 for prices in series.values() if prices[-1] < prices[0])
        dearer = sum(1 for prices in series.values() if prices[-1] > prices[0])

        assert cheaper >= 5
        assert dearer >= 3

    def test_eval_profile_has_an_alert_and_a_shopping_list_for_the_action_cases(
        self, seeded: Session
    ) -> None:
        alerts = seeded.exec(
            select(func.count()).select_from(PriceAlert).where(col(PriceAlert.status) == "active")
        ).one()
        items = seeded.exec(select(func.count()).select_from(ShoppingListItem)).one()

        assert alerts >= 1  # C05 (list_alerts)
        assert items >= 1

    def test_first_wireless_mouse_of_a01_has_a_price_history_for_c04(self, seeded: Session) -> None:
        first = ProductRepository(seeded).search(build_query(CASES_BY_ID["A01"])).items[0]
        assert first.product.id is not None

        points = seeded.exec(
            select(func.count())
            .select_from(PriceHistory)
            .join(Offer, col(PriceHistory.offer_id) == col(Offer.id))
            .where(col(Offer.product_id) == first.product.id)
        ).one()

        assert points >= 3
