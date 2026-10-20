"""Ghép offer vào Product ở pipeline (T5.2): idempotent, chéo trang, http/https, hai nhóm."""

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer, Product
from app.db.repositories import ProductRepository
from app.domain.dto import ListingItem, ProductDetail
from app.domain.enums import Category, MatchMethod, ScrapeStatus, ScrapeTrigger, SiteKey
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import Resolution, ScrapePipeline, resolve_product
from tests.integration.test_pipeline import Clock, ScriptedFetcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GEARVN = "https://gearvn.com"
GEARVN_MOUSES = f"{GEARVN}/collections/chuot-may-tinh"
GEARVN_KEYBOARDS = f"{GEARVN}/collections/ban-phim-may-tinh"
ANPHAT_MOUSES = "https://www.anphatpc.com.vn/chuot-may-tinh_dm1291.html"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def served(url: str, site: str, name: str, *, final_url: str | None = None) -> FetchResponse:
    text = (FIXTURES / site / name).read_text(encoding="utf-8")
    return FetchResponse(url=url, final_url=final_url or url, status=200, text=text)


def gearvn_mice(*, final_url: str | None = None) -> ScriptedFetcher:
    return ScriptedFetcher(
        {
            GEARVN_MOUSES: served(
                GEARVN_MOUSES, "gearvn", "listing_mouse_p1.html", final_url=final_url
            )
        }
    )


def anphat_mice() -> ScriptedFetcher:
    return ScriptedFetcher(
        {ANPHAT_MOUSES: served(ANPHAT_MOUSES, "anphat", "listing_mouse_p1.html")}
    )


async def scrape(
    factory: Callable[[], Session],
    clock: Clock,
    fetcher: ScriptedFetcher,
    site: SiteKey,
    category: Category = Category.mouse,
) -> None:
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)
    result = await pipe.run(site, category, ScrapeTrigger.test, max_pages=1)
    assert result.status is ScrapeStatus.PARTIAL and result.items_failed == 0


def all_offers(session: Session) -> list[Offer]:
    session.expire_all()
    return list(session.exec(select(Offer).order_by(col(Offer.id))))


def all_products(session: Session) -> list[Product]:
    session.expire_all()
    return list(session.exec(select(Product).order_by(col(Product.id))))


def offers_of(session: Session, fragment: str) -> list[Offer]:
    return [offer for offer in all_offers(session) if fragment in offer.title]


async def test_colour_variants_on_one_site_share_a_product(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await scrape(factory, clock, gearvn_mice(), SiteKey.gearvn)

    for model in ("AKKO Nest", "AKKO Dash V9 Max"):
        colours = offers_of(db_session, model)
        assert len(colours) == 2
        assert len({offer.product_id for offer in colours}) == 1
    superstrike = offers_of(db_session, "Pro X3 Superstrike Lightspeed")
    assert len(superstrike) == 2  # Black và Pink
    assert len({offer.product_id for offer in superstrike}) == 1
    assert {offer.match_method for offer in superstrike} == {MatchMethod.new, MatchMethod.fuzzy}
    assert len(all_products(db_session)) < len(all_offers(db_session))


async def test_rerun_creates_no_new_product_or_offer_and_keeps_match_info(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await scrape(factory, clock, gearvn_mice(), SiteKey.gearvn)
    first_products = [
        (p.id, p.canonical_name, p.specs_confidence) for p in all_products(db_session)
    ]
    first_offers = [
        (o.id, o.product_id, o.match_method, o.match_score) for o in all_offers(db_session)
    ]

    await scrape(factory, clock, gearvn_mice(), SiteKey.gearvn)

    assert [(p.id, p.canonical_name, p.specs_confidence) for p in all_products(db_session)] == (
        first_products
    )
    assert [
        (o.id, o.product_id, o.match_method, o.match_score) for o in all_offers(db_session)
    ] == first_offers


async def test_same_mouse_on_two_sites_becomes_one_product_with_two_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await scrape(factory, clock, gearvn_mice(), SiteKey.gearvn)
    await scrape(factory, clock, anphat_mice(), SiteKey.anphat)

    g304 = [o for o in all_offers(db_session) if "G304 X Superlight" in o.title]
    assert {o.site for o in g304} == {SiteKey.gearvn, SiteKey.anphat}
    assert len({o.product_id for o in g304}) == 1
    anphat = [o for o in g304 if o.site is SiteKey.anphat]
    assert {o.match_method for o in anphat} == {MatchMethod.fuzzy}
    assert all(o.match_score is not None and o.match_score >= 0.9 for o in anphat)

    # Mẫu chỉ có ở một trang thì giữ nguyên là sản phẩm riêng.
    assert len({o.product_id for o in offers_of(db_session, "G102 Gen2")}) == 1
    products = {p.id: p for p in all_products(db_session)}
    product = products[g304[0].product_id]
    assert product.brand == "Logitech"
    assert product.canonical_name == "Logitech G304 X Superlight"


async def test_http_and_https_forms_of_one_url_are_one_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await scrape(factory, clock, gearvn_mice(), SiteKey.gearvn)
    before = [(o.id, o.url, o.product_id) for o in all_offers(db_session)]
    assert all(url.startswith("https://") for _, url, _ in before)

    # Lần sau trang trả cùng sản phẩm với liên kết http://.
    await scrape(
        factory,
        clock,
        gearvn_mice(final_url="http://gearvn.com/collections/chuot-may-tinh"),
        SiteKey.gearvn,
    )

    assert [(o.id, o.url, o.product_id) for o in all_offers(db_session)] == before


async def test_same_url_listed_in_two_categories_keeps_the_first_product(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await scrape(factory, clock, gearvn_mice(), SiteKey.gearvn)
    offers_before = [(o.id, o.product_id, o.is_active) for o in all_offers(db_session)]
    products_before = len(all_products(db_session))

    # Cùng trang HTML được liệt kê lại ở nhóm bàn phím.
    keyboard_fetcher = ScriptedFetcher(
        {GEARVN_KEYBOARDS: served(GEARVN_KEYBOARDS, "gearvn", "listing_mouse_p1.html")}
    )
    await scrape(factory, clock, keyboard_fetcher, SiteKey.gearvn, Category.keyboard)

    assert [(o.id, o.product_id, o.is_active) for o in all_offers(db_session)] == offers_before
    assert len(all_products(db_session)) == products_before
    assert {p.category for p in all_products(db_session)} == {Category.mouse}


async def test_unique_model_key_collision_fails_only_that_item(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    def colliding_resolver(
        session: Session,
        category: Category,
        item: ListingItem,
        detail: ProductDetail | None,
        raw_specs: Mapping[str, str],
    ) -> Resolution:
        if "AKKO Nest Black" in item.title:
            repo = ProductRepository(session)
            for _ in range(2):  # lần thứ hai vi phạm chỉ mục unique (category, brand, model_code)
                repo.add(
                    Product(category=category, brand="Akko", model_code="DUP-1", canonical_name="d")
                )
        return resolve_product(session, category, item, detail, raw_specs)

    pipe = ScrapePipeline(factory, gearvn_mice(), now=clock, resolver=colliding_resolver)

    result = await pipe.run(SiteKey.gearvn, Category.mouse, ScrapeTrigger.test, max_pages=1)

    assert result.items_failed == 1  # chỉ mục va chạm; cả lượt không dừng
    assert result.offers_upserted == result.items_parsed - 1
    assert not [o for o in all_offers(db_session) if "AKKO Nest Black" in o.title]
    # Savepoint của mục lỗi được rollback, kể cả Product thứ nhất vừa thêm.
    assert not [p for p in all_products(db_session) if p.model_code == "DUP-1"]
