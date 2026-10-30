"""QA small-fixes-4: `resolve_product` bù `image_url` cho sản phẩm đã có, không ghi đè (T5.4a)."""

from sqlmodel import Session

from app.db.models import Offer, Product
from app.db.repositories import OfferRepository, OfferUpsert, ProductRepository
from app.domain.dto import ListingItem
from app.domain.enums import Category, SiteKey
from app.normalize.url import clean_url
from app.scrapers.pipeline import resolve_product

BASE = "https://shop.example"
IMG_A = "https://img.example/a.jpg"
IMG_B = "https://img.example/b.jpg"


def item(slug: str, title: str, image: str | None = None) -> ListingItem:
    return ListingItem(
        site=SiteKey.gearvn,
        url=f"{BASE}/p/{slug}",
        title=title,
        price=1_000_000,
        raw_specs={"Ghi chú": "x"},
        image_url=image,
    )


def store(session: Session, row: ListingItem, product_id: int) -> Offer:
    return (
        OfferRepository(session)
        .upsert(
            OfferUpsert(
                product_id=product_id,
                site=SiteKey.gearvn,
                url=clean_url(str(row.url)),
                title=row.title,
                price=1_000_000,
            )
        )
        .offer
    )


def image_of(session: Session, product_id: int) -> str | None:
    session.expire_all()
    product = ProductRepository(session).get(product_id)
    assert product is not None
    return product.image_url


def test_a_new_product_takes_the_image_of_its_first_offer(db_session: Session) -> None:
    resolution = resolve_product(
        db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red", IMG_A), None
    )

    assert image_of(db_session, resolution.product_id) == IMG_A


def test_a_new_product_without_an_image_stays_empty_until_a_later_offer_brings_one(
    db_session: Session,
) -> None:
    first = resolve_product(db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red"), None)
    assert image_of(db_session, first.product_id) is None

    second = resolve_product(
        db_session, Category.mouse, item("b", "Chuột Pulsar X2 Black", IMG_B), None
    )

    assert second.product_id == first.product_id
    assert image_of(db_session, first.product_id) == IMG_B


def test_rescraping_an_existing_offer_fills_a_missing_product_image(db_session: Session) -> None:
    first = resolve_product(db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red"), None)
    assert image_of(db_session, first.product_id) is None
    store(db_session, item("a", "Chuột Pulsar X2 Red"), first.product_id)

    again = resolve_product(
        db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red", IMG_A), None
    )

    assert again.product_id == first.product_id
    assert image_of(db_session, first.product_id) == IMG_A


def test_rescraping_an_existing_offer_never_replaces_or_clears_the_product_image(
    db_session: Session,
) -> None:
    first = resolve_product(
        db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red", IMG_A), None
    )
    store(db_session, item("a", "Chuột Pulsar X2 Red"), first.product_id)

    resolve_product(db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red", IMG_B), None)
    assert image_of(db_session, first.product_id) == IMG_A
    resolve_product(db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red"), None)
    assert image_of(db_session, first.product_id) == IMG_A


def test_an_offer_already_stored_under_another_category_does_not_lend_its_image_to_that_product(
    db_session: Session,
) -> None:
    laptop = ProductRepository(db_session).add(
        Product(
            category=Category.laptop,
            brand="Acer",
            model_code=None,
            canonical_name="Acer Mock",
            specs={},
        )
    )
    assert laptop.id is not None
    store(db_session, item("shared", "Acer Mock"), laptop.id)

    resolution = resolve_product(
        db_session, Category.mouse, item("shared", "Acer Mock", IMG_A), None
    )

    assert resolution.product_id == laptop.id
    assert image_of(db_session, laptop.id) is None


def test_a_fuzzy_matched_product_with_an_image_keeps_it(db_session: Session) -> None:
    first = resolve_product(
        db_session, Category.mouse, item("a", "Chuột Pulsar X2 Red", IMG_A), None
    )

    second = resolve_product(db_session, Category.mouse, item("b", "Pulsar X2 Black", IMG_B), None)

    assert second.product_id == first.product_id
    assert image_of(db_session, first.product_id) == IMG_A
