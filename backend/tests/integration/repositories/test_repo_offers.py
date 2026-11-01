from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlmodel import Session, select

from app.db.models import Offer
from app.db.repositories.offers import OfferRepository, OfferUpsert, effective_price
from app.db.repositories.price_history import PriceHistoryRepository
from app.domain.enums import Category, MatchMethod, PriceType, SiteKey, StockStatus
from tests.factories import make_offer, make_product

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _product(session: Session, **overrides: object) -> int:
    product = make_product(**overrides)
    session.add(product)
    session.flush()
    assert product.id is not None
    return product.id


def _data(product_id: int, **overrides: object) -> OfferUpsert:
    values: dict[str, object] = {
        "product_id": product_id,
        "site": SiteKey.mockshop,
        "url": "https://mock.example/p/a",
        "title": "Mock Laptop A",
        "price": 27_490_000,
    }
    values.update(overrides)
    return OfferUpsert.model_validate(values)


def test_upsert_creates_offer_and_reports_created(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)

    result = repo.upsert(_data(product_id, price_type=PriceType.sale), now=T0)

    assert result.created is True
    assert result.offer.id is not None
    assert result.offer.price == 27_490_000
    assert result.offer.price_type == PriceType.sale
    assert result.offer.first_seen_at == T0
    assert result.offer.scraped_at == T0
    assert result.offer.is_active is True


def test_upsert_same_url_updates_row_and_keeps_id_and_first_seen_at(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)
    first = repo.upsert(_data(product_id), now=T0).offer
    first_id = first.id

    later = T0 + timedelta(hours=3)
    second = repo.upsert(
        _data(
            product_id,
            title="Mock Laptop A (mới)",
            price=25_990_000,
            list_price=27_490_000,
            stock_status=StockStatus.out_of_stock,
            raw_specs={"RAM": "16GB"},
            rating=4.5,
            rating_count=12,
        ),
        now=later,
    )

    assert second.created is False
    assert second.offer.id == first_id
    assert second.offer.price == 25_990_000
    assert second.offer.list_price == 27_490_000
    assert second.offer.title == "Mock Laptop A (mới)"
    assert second.offer.stock_status == StockStatus.out_of_stock
    assert second.offer.raw_specs == {"RAM": "16GB"}
    assert second.offer.rating == 4.5
    assert second.offer.first_seen_at == T0
    assert second.offer.scraped_at == later
    assert db_session.exec(select(Offer)).all() == [second.offer]


def test_upsert_returns_the_instance_already_in_the_session_refreshed(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)
    first = repo.upsert(_data(product_id), now=T0).offer

    second = repo.upsert(_data(product_id, price=1_000_000), now=T0 + timedelta(hours=1)).offer

    assert second is first
    assert first.price == 1_000_000


def test_upsert_reactivates_inactive_offer(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)
    offer = repo.upsert(_data(product_id), now=T0).offer
    offer.is_active = False
    db_session.flush()

    again = repo.upsert(_data(product_id), now=T0 + timedelta(hours=1)).offer

    assert again.is_active is True


def test_upsert_can_move_offer_to_another_product(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    first_product = _product(db_session)
    second_product = _product(db_session)
    repo.upsert(_data(first_product), now=T0)

    moved = repo.upsert(_data(second_product), now=T0 + timedelta(hours=1)).offer

    assert moved.product_id == second_product


def test_upsert_different_urls_create_separate_offers(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)

    first = repo.upsert(_data(product_id, url="https://mock.example/p/a"), now=T0)
    second = repo.upsert(_data(product_id, url="https://mock.example/p/b"), now=T0)

    assert first.created and second.created
    assert first.offer.id != second.offer.id


def test_upsert_data_rejects_negative_price_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _data(1, price=-1)
    with pytest.raises(ValidationError):
        _data(1, colour="red")


def test_get_and_get_by_url(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)
    offer = repo.upsert(_data(product_id), now=T0).offer

    assert repo.get(offer.id) is offer  # type: ignore[arg-type]
    assert repo.get_by_url("https://mock.example/p/a") is offer
    assert repo.get_by_url("https://mock.example/p/zzz") is None
    assert repo.get(999_999_999) is None


@pytest.mark.parametrize(
    ("price_type", "price", "list_price", "expected"),
    [
        (PriceType.regular, 20_000_000, 25_000_000, 20_000_000),
        (PriceType.sale, 20_000_000, 25_000_000, 20_000_000),
        (PriceType.flash, 18_000_000, 25_000_000, 18_000_000),
        (PriceType.unknown, 20_000_000, None, 20_000_000),
        (PriceType.member, 19_000_000, 25_000_000, 25_000_000),
        (PriceType.member, 19_000_000, None, 19_000_000),
    ],
)
def test_effective_price_follows_price_type(
    db_session: Session,
    price_type: PriceType,
    price: int,
    list_price: int | None,
    expected: int,
) -> None:
    product_id = _product(db_session)
    offer = make_offer(product_id, price=price, list_price=list_price, price_type=price_type)
    db_session.add(offer)
    db_session.flush()

    assert db_session.exec(select(effective_price()).where(Offer.id == offer.id)).one() == expected


def test_list_for_product_orders_by_effective_price_and_filters_inactive(
    db_session: Session,
) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)
    other_product = _product(db_session)
    cheap = repo.upsert(_data(product_id, url="https://mock.example/c", price=10), now=T0).offer
    member = repo.upsert(
        _data(
            product_id,
            url="https://mock.example/m",
            price=5,
            list_price=30,
            price_type=PriceType.member,
        ),
        now=T0,
    ).offer
    dear = repo.upsert(_data(product_id, url="https://mock.example/d", price=20), now=T0).offer
    gone = repo.upsert(_data(product_id, url="https://mock.example/g", price=1), now=T0).offer
    gone.is_active = False
    repo.upsert(_data(other_product, url="https://mock.example/o", price=2), now=T0)
    db_session.flush()

    assert repo.list_for_product(product_id) == [cheap, dear, member]
    assert repo.list_for_product(product_id, active_only=False) == [gone, cheap, dear, member]


def test_deactivate_unseen_only_touches_matching_site_category_and_stale_rows(
    db_session: Session,
) -> None:
    repo = OfferRepository(db_session)
    laptop = _product(db_session, category=Category.laptop)
    mouse = _product(db_session, category=Category.mouse)
    cutoff = T0 + timedelta(hours=1)
    stale = repo.upsert(_data(laptop, url="https://mock.example/stale"), now=T0).offer
    fresh = repo.upsert(_data(laptop, url="https://mock.example/fresh"), now=cutoff).offer
    other_site = repo.upsert(
        _data(laptop, url="https://g.example/x", site=SiteKey.gearvn), now=T0
    ).offer
    other_category = repo.upsert(_data(mouse, url="https://mock.example/mouse"), now=T0).offer

    count = repo.deactivate_unseen(SiteKey.mockshop, Category.laptop, cutoff)

    assert count == 1
    assert stale.is_active is False
    assert fresh.is_active is True  # đúng bằng mốc: chưa bị tắt
    assert other_site.is_active is True
    assert other_category.is_active is True


def test_deactivate_unseen_returns_zero_when_nothing_is_stale(db_session: Session) -> None:
    repo = OfferRepository(db_session)

    assert repo.deactivate_unseen(SiteKey.mockshop, Category.laptop, T0) == 0


def test_repeated_upserts_report_created_only_the_first_time(db_session: Session) -> None:
    repo = OfferRepository(db_session)
    product_id = _product(db_session)

    flags = [repo.upsert(_data(product_id), now=T0 + timedelta(hours=h)).created for h in range(3)]

    assert flags == [True, False, False]


def test_upsert_result_feeds_record_snapshot_with_the_new_price(db_session: Session) -> None:
    offers = OfferRepository(db_session)
    history = PriceHistoryRepository(db_session)
    product_id = _product(db_session)
    first = offers.upsert(_data(product_id, price=27_490_000), now=T0)
    history.record_snapshot(first.offer, now=T0)

    second = offers.upsert(_data(product_id, price=25_990_000), now=T0 + timedelta(hours=1))
    result = history.record_snapshot(second.offer, now=T0 + timedelta(hours=1))

    assert result.price_changed is True
    assert (result.previous_price, result.reason) == (27_490_000, "changed")
    assert [row.price for row in history.list_for_offer(second.offer.id)] == [  # type: ignore[arg-type]
        27_490_000,
        25_990_000,
    ]


def test_list_by_category_returns_every_offer_of_the_category_by_id(db_session: Session) -> None:
    laptop = _product(db_session)
    mouse = _product(db_session, category=Category.mouse, model_code=None)
    first = make_offer(laptop, url="https://mock.example/p/a")
    inactive = make_offer(laptop, url="https://mock.example/p/b", is_active=False)
    other = make_offer(mouse, url="https://mock.example/p/c")
    db_session.add_all([first, inactive, other])
    db_session.flush()

    found = OfferRepository(db_session).list_by_category(Category.laptop)

    ids = [o.id for o in found]
    assert first.id in ids and inactive.id in ids and other.id not in ids
    assert ids == sorted(ids)


def test_reassign_moves_the_offer_with_its_new_match(db_session: Session) -> None:
    old, new = _product(db_session), _product(db_session)
    offer = make_offer(old, match_method=MatchMethod.new)
    db_session.add(offer)
    db_session.flush()

    OfferRepository(db_session).reassign(offer, new, MatchMethod.fuzzy, 0.93)
    db_session.expire(offer)

    assert (offer.product_id, offer.match_method, offer.match_score) == (
        new,
        MatchMethod.fuzzy,
        0.93,
    )
