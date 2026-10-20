"""QA M5: pipeline + ghép mẫu trên PostgreSQL thật (tiêu đề tùy ý qua `ScrapePipeline` thật).

Dùng scraper giả đọc danh sách từ JSON để đưa tiêu đề/URL bất kỳ vào pipeline với `resolve_product`
thật. Test `xfail(strict=True)` là lỗi đã tái hiện (mã BUG-M5-n, xem báo cáo QA M5); khi sửa xong,
XPASS làm test đỏ và phải gỡ dấu xfail.
"""

import json
import re
import time
from collections.abc import Callable
from typing import Any, ClassVar

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer, Product
from app.db.repositories import OfferRepository, OfferUpsert, ProductRepository
from app.domain.dto import ListingItem, ListingPage
from app.domain.enums import Category, MatchMethod, ScrapeStatus, ScrapeTrigger, SiteKey
from app.normalize.url import clean_url
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.pipeline import (
    PipelineResult,
    ScrapePipeline,
    find_existing_offer,
    resolve_product,
)
from app.scrapers.registry import SCRAPERS
from tests.integration.test_pipeline import Clock, ScriptedFetcher, page

BASE = "https://shop.example"
MOUSE_LISTING = f"{BASE}/c/mouse"
LAPTOP_LISTING = f"{BASE}/c/laptop"
GENERIC_SPECS = {"Ghi chú": "x"}  # có bảng thông số thì pipeline không tải trang chi tiết
ACER = "Laptop Acer Aspire Lite 15 AL15-53P-56QH"


def bug(code: str, why: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{code}: {why}")


class JsonListingScraper(BaseScraper):
    """Trang "thật" giả: danh sách là một mảng JSON trong `<script id="items">`."""

    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.gearvn,
        base_url=BASE,
        min_delay_s=5.0,
        categories={Category.mouse: MOUSE_LISTING, Category.laptop: LAPTOP_LISTING},
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        match = re.search(r'<script id="items">(.*?)</script>', html, re.DOTALL)
        assert match is not None
        items = [
            ListingItem.model_validate(
                {
                    "site": SiteKey.gearvn,
                    "price": 1_000_000,
                    "raw_specs": GENERIC_SPECS,
                    **entry,
                }
            )
            for entry in json.loads(match.group(1))
        ]
        return ListingPage(items=items, has_next=False)


@pytest.fixture(autouse=True)
def json_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SCRAPERS, SiteKey.gearvn, JsonListingScraper)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def entry(slug: str, title: str, **extra: Any) -> dict[str, Any]:
    return {"url": f"{BASE}/p/{slug}", "title": title, **extra}


async def scrape(
    factory: Callable[[], Session],
    clock: Clock,
    entries: list[dict[str, Any]],
    category: Category = Category.mouse,
) -> PipelineResult:
    url = MOUSE_LISTING if category is Category.mouse else LAPTOP_LISTING
    html = f'<html><script id="items">{json.dumps(entries)}</script></html>'
    pipe = ScrapePipeline(
        factory, ScriptedFetcher({url: page(html, url)}), now=clock, default_max_pages=5
    )
    return await pipe.run(SiteKey.gearvn, category, ScrapeTrigger.test)


def offers(session: Session) -> list[Offer]:
    session.expire_all()
    return list(session.exec(select(Offer).order_by(col(Offer.id))))


def products(session: Session) -> list[Product]:
    session.expire_all()
    return list(session.exec(select(Product).order_by(col(Product.id))))


def offer_for(session: Session, slug: str) -> Offer:
    (found,) = [o for o in offers(session) if o.url.endswith(f"/p/{slug}")]
    return found


# ---- tiêu đề độc ----
async def test_a_title_with_a_nul_character_fails_only_that_item_and_leaves_no_orphan_product(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    result = await scrape(
        factory,
        clock,
        [
            entry("good-1", "Chuột Pulsar X2 Red"),
            entry("nul", "Chuột Pulsar\x00 X2 Black"),
            entry("good-2", "Chuột Razer Viper V3 Pro"),
        ],
    )

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (3, 1, 2)
    assert {o.url.rsplit("/", 1)[1] for o in offers(db_session)} == {"good-1", "good-2"}
    assert sorted(p.canonical_name for p in products(db_session)) == [
        "Pulsar X2",
        "Razer Viper V3 Pro",
    ]


async def test_a_nul_in_the_spec_table_fails_only_that_item(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    result = await scrape(
        factory,
        clock,
        [
            entry("bad", "Chuột Pulsar X2 Red", raw_specs={"Cảm biến": "PAW\x003395"}),
            entry("good", "Chuột Razer Viper V3 Pro"),
        ],
    )

    assert (result.items_failed, result.offers_upserted) == (1, 1)
    assert [p.canonical_name for p in products(db_session)] == ["Razer Viper V3 Pro"]


async def test_a_huge_title_is_stored_and_matched_without_error(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    huge = "Chuột Pulsar X2 " + "Black " * 50_000

    started = time.perf_counter()
    result = await scrape(factory, clock, [entry("huge", huge), entry("plain", "Chuột Pulsar X2")])

    assert time.perf_counter() - started < 10
    assert (result.items_failed, result.offers_upserted) == (0, 2)
    assert len(offers(db_session)) == 2
    assert all(len(p.canonical_name) <= 2000 for p in products(db_session))


# ---- chạy lại, đổi tiêu đề ----
async def test_rerun_after_cosmetic_title_changes_keeps_products_and_match_info(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await scrape(
        factory,
        clock,
        [entry("red", "Chuột Pulsar X2 Red"), entry("black", "Chuột Pulsar X2 Black")],
    )
    before = {
        o.url: (o.id, o.product_id, o.match_method, o.match_score) for o in offers(db_session)
    }
    assert {method for *_, method, _ in before.values()} == {MatchMethod.new, MatchMethod.fuzzy}

    result = await scrape(
        factory,
        clock,
        [
            entry("red", "[Hot] Chuột Pulsar X2 Red - Chính hãng"),
            entry("black", "CHUỘT PULSAR X2 BLACK (Mới 100%)"),
        ],
    )

    assert result.items_failed == 0
    after = {o.url: (o.id, o.product_id, o.match_method, o.match_score) for o in offers(db_session)}
    assert after == before
    assert len(products(db_session)) == 1
    assert offer_for(db_session, "red").title == "[Hot] Chuột Pulsar X2 Red - Chính hãng"


async def test_rerun_fills_specs_that_a_later_title_reveals_but_never_overwrites(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await scrape(factory, clock, [entry("a", "Chuột Pulsar X2 Wireless")])
    (product,) = products(db_session)
    assert product.specs == {"connection": ["wireless_2_4"]}

    await scrape(factory, clock, [entry("a", "Chuột có dây Pulsar X2 26000 DPI 60g")])

    (product,) = products(db_session)
    assert product.specs["connection"] == ["wireless_2_4"]  # giá trị cũ được giữ
    assert (product.specs["dpi_max"], product.specs["weight_g"]) == (26000, 60)  # trường mới điền


# ---- hai offer cùng lượt ----
async def test_offers_with_the_same_laptop_code_in_one_listing_share_a_product_until_specs_differ(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    result = await scrape(
        factory,
        clock,
        [
            entry("a", f"{ACER} (Core 5-120U/ 8GB/ 512GB/ Intel Graphics)"),
            entry("b", f"{ACER} Core 5 120U/8GB/512GB"),
            entry("c", f"{ACER} (Core 5-120U/ 16GB/ 512GB/ Intel Graphics)"),
            entry("d", f"{ACER} Core 5 120U/16GB/512GB/Intel Graphics"),
        ],
        Category.laptop,
    )

    assert (result.items_failed, result.offers_upserted) == (0, 4)
    a, b, c, d = (offer_for(db_session, slug) for slug in "abcd")
    assert a.product_id == b.product_id
    assert (b.match_method, b.match_score) == (MatchMethod.model_code, 1.0)
    assert c.product_id not in {a.product_id, b.product_id}  # 16 GB khác 8 GB nên là mẫu khác
    assert d.product_id == c.product_id and d.match_method is MatchMethod.fuzzy
    coded, codeless = (p for p in products(db_session))
    assert (coded.model_code, codeless.model_code) == ("AL15-53P-56QH", None)
    assert (coded.specs["ram_gb"], codeless.specs["ram_gb"]) == (8, 16)


async def test_same_site_sku_title_twice_in_one_listing_with_different_urls_stays_two_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    result = await scrape(
        factory,
        clock,
        [entry("one", "Chuột Pulsar X2 Red"), entry("two", "Chuột Pulsar X2 Red")],
    )

    assert result.offers_upserted == 2
    assert len({o.product_id for o in offers(db_session)}) == 1
    assert len(products(db_session)) == 1


# ---- URL: query, cổng, scheme ----
async def test_url_variants_collapse_to_one_offer_and_distinct_queries_stay_distinct(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    first = await scrape(
        factory,
        clock,
        [
            {"url": f"{BASE}/p/q?a=1&b=2", "title": "Chuột Pulsar X2 Red"},
            {"url": f"{BASE}/p/id?id=1", "title": "Chuột Razer Viper V3 Pro"},
            {"url": f"{BASE}/p/id?id=2", "title": "Chuột Razer DeathAdder V3 Pro"},
            {"url": "http://shop.example/p/h", "title": "Chuột Logitech G304 X Superlight"},
            {"url": "https://shop.example/p/h", "title": "Chuột Logitech G304 X Superlight"},
        ],
    )
    assert (first.items_parsed, first.offers_upserted) == (5, 4)  # http/https của /p/h là một
    stored = {o.url: o.id for o in offers(db_session)}
    assert len(stored) == 4

    second = await scrape(
        factory,
        clock,
        [
            {
                "url": "https://SHOP.example:443/p/q?b=2&a=1&utm_source=fb#top",
                "title": "Chuột Pulsar X2 Red",
            },
            {"url": f"{BASE}/p/id?id=1&gclid=abc", "title": "Chuột Razer Viper V3 Pro"},
            {"url": f"{BASE}/p/id?id=2", "title": "Chuột Razer DeathAdder V3 Pro"},
            {"url": "https://shop.example/p/h", "title": "Chuột Logitech G304 X Superlight"},
        ],
    )

    assert second.items_failed == 0
    assert {o.url: o.id for o in offers(db_session)} == stored
    assert len(products(db_session)) == 4


async def test_item_url_outside_the_site_fails_before_a_product_is_created(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    result = await scrape(
        factory,
        clock,
        [
            {"url": "https://evil.example/p/x", "title": "Chuột Pulsar X2 Red"},
            entry("ok", "Chuột Razer Viper V3 Pro"),
        ],
    )

    assert (result.items_failed, result.offers_upserted) == (1, 1)
    assert [p.canonical_name for p in products(db_session)] == ["Razer Viper V3 Pro"]


# ---- dữ liệu Product đã lưu hỏng ----
def add_corrupted_logitech(session: Session, specs: dict[str, Any]) -> None:
    ProductRepository(session).add(
        Product(
            category=Category.mouse,
            brand="Logitech",
            canonical_name="Logitech G304 Lightspeed",
            specs=specs,
        )
    )


def mouse_item(slug: str, title: str) -> ListingItem:
    return ListingItem(
        site=SiteKey.gearvn,
        url=f"{BASE}/p/{slug}",
        title=title,
        price=1_000_000,
        raw_specs=GENERIC_SPECS,
    )


@pytest.mark.parametrize(
    "specs",
    [
        {"connection": "wired", "dpi_max": "26000"},
        {"connection": 5, "buttons": [6]},
        {"weight_g": {}},
    ],
    ids=["strings", "scalars", "dict-value"],
)
def test_matching_against_a_product_with_wrong_typed_specs_does_not_crash(
    db_session: Session, specs: dict[str, Any]
) -> None:
    add_corrupted_logitech(db_session, specs)

    resolution = resolve_product(
        db_session,
        Category.mouse,
        mouse_item("new", "Chuột Logitech G304 Lightspeed 26000 DPI"),
        None,
    )

    assert resolution.method in {MatchMethod.new, MatchMethod.fuzzy}
    assert resolution.product_id is not None


def test_enriching_an_existing_offer_repairs_wrong_typed_specs_of_its_product(
    db_session: Session,
) -> None:
    repo = ProductRepository(db_session)
    product = repo.add(
        Product(
            category=Category.mouse,
            brand="Logitech",
            canonical_name="Logitech G304",
            specs={"connection": "wired", "dpi_max": "26000", "weight_g": [99]},
            specs_confidence=1.0,
        )
    )
    assert product.id is not None
    OfferRepository(db_session).upsert(
        OfferUpsert(
            product_id=product.id,
            site=SiteKey.gearvn,
            url=f"{BASE}/p/g304",
            title="Chuột Logitech G304",
            price=1_000_000,
        )
    )

    resolve_product(
        db_session,
        Category.mouse,
        mouse_item("g304", "Chuột không dây Logitech G304 26000 DPI 99g"),
        None,
    )

    db_session.refresh(product)
    assert product.specs == {"connection": ["wireless_2_4"], "dpi_max": 26000, "weight_g": 99}
    assert product.specs_confidence == 1.0


async def test_one_product_with_nested_list_specs_must_not_fail_the_whole_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    add_corrupted_logitech(db_session, {"connection": [["wired"]]})

    result = await scrape(
        factory,
        clock,
        [
            entry("g304", "Chuột Logitech G304 Lightspeed"),
            entry("viper", "Chuột Razer Viper V3 Pro"),
        ],
    )

    assert result.status is not ScrapeStatus.FAILED
    assert result.offers_upserted == 2


# ---- hiệu năng ----
def test_loading_and_matching_against_hundreds_of_products_of_one_brand_is_fast(
    db_session: Session,
) -> None:
    db_session.add_all(
        Product(
            category=Category.mouse,
            brand="Logitech",
            canonical_name=f"Logitech G{n} Lightspeed",
            specs={"connection": ["wireless_2_4"], "dpi_max": 25000, "sensor": "HERO"},
        )
        for n in range(1, 501)
    )
    db_session.flush()

    started = time.perf_counter()
    loaded = ProductRepository(db_session).list_by_brand(Category.mouse, "Logitech")
    for n in range(20):
        resolve_product(
            db_session,
            Category.mouse,
            mouse_item(f"perf-{n}", f"Chuột Logitech G{n + 1} Lightspeed"),
            None,
        )
    elapsed = time.perf_counter() - started

    assert [p.id for p in loaded] == sorted(p.id for p in loaded if p.id is not None)
    assert len(loaded) == 500
    assert len(ProductRepository(db_session).list_by_brand(Category.mouse, "Logitech")) == 500
    assert elapsed < 10, f"{elapsed:.2f}s"


# ---- cổng riêng, ảnh ----
def test_explicit_port_urls_keep_the_port_and_http_never_pairs_with_https(
    db_session: Session,
) -> None:
    product = ProductRepository(db_session).add(
        Product(category=Category.mouse, brand="Pulsar", canonical_name="Pulsar X2")
    )
    assert product.id is not None
    offers_repo = OfferRepository(db_session)
    stored = offers_repo.upsert(
        OfferUpsert(
            product_id=product.id,
            site=SiteKey.mockshop,
            url=clean_url("http://localhost:8100/p/x"),
            title="Chuột Pulsar X2",
            price=1_000_000,
        )
    ).offer

    same = find_existing_offer(offers_repo, clean_url("http://LOCALHOST:8100/p/x?utm_source=a#top"))
    other_scheme = find_existing_offer(offers_repo, clean_url("https://localhost:8100/p/x"))
    default_port = find_existing_offer(offers_repo, clean_url("http://localhost:80/p/x"))

    assert same == stored
    assert other_scheme is None  # hai cổng tùy chọn của http và https là hai máy chủ khác nhau
    assert default_port is None  # :80 bị bỏ nên là máy chủ khác :8100


@bug(
    "BUG-M5-14",
    "resolve_product chỉ đặt Product.image_url lúc tạo (pipeline.py:221) và _enrich không bù ảnh; "
    "Offer không có cột ảnh nên nếu offer đầu tiên thiếu ảnh thì sản phẩm không bao giờ có ảnh dù "
    "các offer ghép sau có",
)
def test_a_later_offer_with_an_image_fills_the_missing_product_image(db_session: Session) -> None:
    first = mouse_item("red", "Chuột Pulsar X2 Red")
    second = mouse_item("black", "Chuột Pulsar X2 Black").model_copy(
        update={"image_url": "https://img.example/x2.jpg"}
    )

    res_first = resolve_product(db_session, Category.mouse, first, None)
    res_second = resolve_product(db_session, Category.mouse, second, None)

    assert res_second.product_id == res_first.product_id
    product = ProductRepository(db_session).get(res_first.product_id)
    assert product is not None and product.image_url == "https://img.example/x2.jpg"
