"""QA X1: điện thoại qua `resolve_product` và `make rematch` (PostgreSQL thật, rollback).

Test `xfail(strict=True)` mã `BUG-X1-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail. Dữ liệu hư cấu, không gọi mạng.
"""

from typing import Any

from sqlmodel import Session, col, select

from app.db.models import Offer, Product
from app.db.repositories import OfferRepository, OfferUpsert, ProductRepository
from app.domain.dto import ListingItem, ProductDetail
from app.domain.enums import Category, MatchMethod, SiteKey
from app.scrapers.pipeline import Resolution, resolve_product
from app.services.rematch_service import RematchService
from tests.factories import make_shopping_list, make_shopping_list_item
from tests.integration.test_rematch_service import offer, owner_of, product

PHONE = Category.phone


def item(title: str, site: SiteKey, slug: str, **raw_specs: str) -> ListingItem:
    return ListingItem(
        site=site,
        url=f"https://{site.value}.example/p/{slug}",
        title=title,
        price=10_000_000,
        raw_specs=raw_specs,
        category_hint=PHONE,
    )


def store(session: Session, resolution: Resolution, listing: ListingItem) -> None:
    OfferRepository(session).upsert(
        OfferUpsert(
            product_id=resolution.product_id,
            site=listing.site,
            url=str(listing.url),
            title=listing.title,
            price=10_000_000,
            match_method=resolution.method,
            match_score=resolution.score,
        )
    )


def ingest(
    session: Session, listing: ListingItem, detail: ProductDetail | None = None
) -> Resolution:
    resolution = resolve_product(session, PHONE, listing, detail)
    store(session, resolution, listing)
    return resolution


def count_products(session: Session) -> int:
    return len(session.exec(select(Product.id).where(Product.category == PHONE)).all())


def specs_of(session: Session, resolution: Resolution) -> dict[str, Any]:
    row = ProductRepository(session).get(resolution.product_id)
    assert row is not None
    return dict(row.specs)


# ---- pipeline: ghép chéo hai trang ----
def test_the_same_iphone_on_two_sites_is_one_product_and_gains_the_missing_ram(
    db_session: Session,
) -> None:
    fpt = item("Điện thoại iPhone 16 128GB", SiteKey.fptshop, "a", **{"Dung lượng RAM": "8 GB"})
    nk = item("Điện thoại iPhone 16 128GB Đen (MYE73ZP/A)", SiteKey.nguyenkim, "b")

    first = ingest(db_session, fpt)
    second = ingest(db_session, nk)

    assert second.product_id == first.product_id
    assert second.method is MatchMethod.fuzzy
    assert specs_of(db_session, second) == {"ram_gb": 8, "storage_gb": 128}
    assert count_products(db_session) == 1


def test_storage_and_model_variants_stay_separate_products(db_session: Session) -> None:
    titles = [
        "Điện thoại iPhone 16 128GB",
        "Điện thoại iPhone 16 256GB",
        "Điện thoại iPhone 16 Plus 128GB",
        "Điện thoại iPhone 16e 128GB",
        "Điện thoại iPhone 16 Pro 128GB",
    ]
    ids = {
        ingest(db_session, item(t, SiteKey.nguyenkim, f"v{n}")).product_id
        for n, t in enumerate(titles)
    }
    assert len(ids) == len(titles)


def test_resolving_the_same_offer_twice_is_idempotent(db_session: Session) -> None:
    listing = item("Điện thoại Samsung Galaxy A57 5G 8GB/128GB Xanh", SiteKey.nguyenkim, "a")
    first = ingest(db_session, listing)
    again = resolve_product(db_session, PHONE, listing, None)

    assert (again.product_id, again.method) == (first.product_id, first.method)
    assert count_products(db_session) == 1
    assert len(db_session.exec(select(Offer.id)).all()) == 1


def test_a_table_value_that_contradicts_the_title_keeps_the_title_value(
    db_session: Session,
) -> None:
    listing = item(
        "Điện thoại Samsung Galaxy A57 5G 8GB/128GB",
        SiteKey.fptshop,
        "a",
        RAM="12 GB",
        **{"Bộ nhớ trong": "512 GB"},
    )
    resolution = ingest(db_session, listing)
    assert specs_of(db_session, resolution) == {"ram_gb": 8, "storage_gb": 128}


def test_brand_hint_of_the_detail_page_names_a_phone_whose_title_has_no_brand(
    db_session: Session,
) -> None:
    listing = item("Điện thoại Reno16 F 5G 8GB/256GB", SiteKey.nguyenkim, "a")
    detail = ProductDetail(url=str(listing.url), brand_hint="OPPO", model_code_hint="CPH2859-8/256")
    resolution = resolve_product(db_session, PHONE, listing, detail)

    row = ProductRepository(db_session).get(resolution.product_id)
    assert row is not None
    # Điện thoại không dùng mã model của nhà bán để ghép hay lưu.
    assert (row.brand, row.model_code) == ("OPPO", None)


def test_unknown_brand_phones_from_two_sites_are_kept_apart(db_session: Session) -> None:
    first = ingest(db_session, item("Điện thoại Mock X 8GB/256GB Đen", SiteKey.fptshop, "a"))
    second = ingest(db_session, item("Điện thoại Mock X 8GB/256GB Trắng", SiteKey.nguyenkim, "b"))
    assert first.product_id != second.product_id


def test_a_phone_resolved_for_a_laptop_category_url_does_not_move_between_categories(
    db_session: Session,
) -> None:
    listing = item("Điện thoại iPhone 16 128GB", SiteKey.nguyenkim, "a")
    first = ingest(db_session, listing)
    again = resolve_product(db_session, Category.laptop, listing, None)
    assert again.product_id == first.product_id
    row = ProductRepository(db_session).get(first.product_id)
    assert row is not None and row.category is PHONE
    assert "ram_gb" not in row.specs


# ---- rematch ----
def snapshot(session: Session) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    session.expire_all()
    offers = session.exec(select(Offer.id, Offer.product_id).order_by(col(Offer.id))).all()
    products = session.exec(
        select(Product.id, Product.brand, Product.canonical_name, Product.specs).order_by(
            col(Product.id)
        )
    ).all()
    return [tuple(o) for o in offers], [tuple(p) for p in products]


def test_one_product_holding_two_storage_sizes_is_split_and_the_second_run_changes_nothing(
    db_session: Session,
) -> None:
    both = product(
        db_session,
        PHONE,
        brand="Apple",
        canonical_name="iPhone 16 128GB",
        specs={"storage_gb": 128},
    )
    small = offer(db_session, both, "Điện thoại iPhone 16 128GB Đen", site=SiteKey.fptshop)
    big = offer(db_session, both, "Điện thoại iPhone 16 256GB Đen", site=SiteKey.nguyenkim)

    report = RematchService(db_session).run([PHONE], apply=True)

    assert report.products_created == 1
    assert owner_of(db_session, small) == both.id
    assert owner_of(db_session, big) != both.id
    new_product = db_session.get(Product, owner_of(db_session, big))
    assert new_product is not None
    assert new_product.canonical_name == "iPhone 16 256GB"
    assert new_product.specs["storage_gb"] == 256
    after = snapshot(db_session)
    again = RematchService(db_session).run([PHONE], apply=True)
    assert not again.changed
    assert snapshot(db_session) == after


def test_the_same_phone_split_by_colour_is_merged_and_dry_run_writes_nothing(
    db_session: Session,
) -> None:
    black = product(
        db_session,
        PHONE,
        brand="Apple",
        canonical_name="iPhone 16 128GB Đen",
        specs={"storage_gb": 128},
    )
    white = product(
        db_session, PHONE, brand="Unknown", canonical_name="iPhone 16 128GB Trắng", specs={}
    )
    offer(db_session, black, "Điện thoại iPhone 16 128GB Đen", site=SiteKey.fptshop)
    moved = offer(db_session, white, "Điện thoại iPhone 16 128GB Trắng", site=SiteKey.nguyenkim)
    before = snapshot(db_session)

    dry = RematchService(db_session).run([PHONE])
    assert dry.changed and snapshot(db_session) == before

    applied = RematchService(db_session).run([PHONE], apply=True)
    assert owner_of(db_session, moved) == black.id
    assert applied.products_deleted == [white.id]
    assert not RematchService(db_session).run([PHONE], apply=True).changed


def test_rematch_keeps_seeded_specs_that_the_titles_do_not_state(db_session: Session) -> None:
    seeded = product(
        db_session,
        PHONE,
        brand="Apple",
        canonical_name="iPhone 16 128GB",
        specs={"ram_gb": 8, "storage_gb": 128, "chipset": "Apple A18", "os": "iOS 18"},
    )
    offer(db_session, seeded, "Điện thoại iPhone 16 128GB Đen", site=SiteKey.nguyenkim)

    RematchService(db_session).run([PHONE], apply=True)

    db_session.refresh(seeded)
    assert seeded.specs["ram_gb"] == 8
    assert seeded.specs["chipset"] == "Apple A18"
    assert seeded.specs["os"] == "iOS 18"
    assert not RematchService(db_session).run([PHONE], apply=True).changed


def test_a_phone_rematch_leaves_other_categories_untouched(db_session: Session) -> None:
    mouse = product(db_session, Category.mouse, brand="Unknown", canonical_name="Chuột Pulsar X2")
    row = offer(db_session, mouse, "Chuột Pulsar X2 Red")
    phone = product(db_session, PHONE, brand="Apple", canonical_name="iPhone 16 128GB", specs={})
    offer(db_session, phone, "Điện thoại iPhone 16 128GB", site=SiteKey.nguyenkim)

    RematchService(db_session).run([PHONE], apply=True)

    db_session.refresh(mouse)
    assert (mouse.brand, mouse.canonical_name) == ("Unknown", "Chuột Pulsar X2")
    assert owner_of(db_session, row) == mouse.id


def test_a_merged_away_phone_in_a_shopping_list_is_kept(db_session: Session) -> None:
    keep = product(db_session, PHONE, brand="Apple", canonical_name="iPhone 16 128GB", specs={})
    listed = product(
        db_session, PHONE, brand="Unknown", canonical_name="iPhone 16 128GB Trắng", specs={}
    )
    offer(db_session, keep, "Điện thoại iPhone 16 128GB Đen", site=SiteKey.fptshop)
    moved = offer(db_session, listed, "Điện thoại iPhone 16 128GB Trắng", site=SiteKey.nguyenkim)
    shopping_list = make_shopping_list()
    db_session.add(shopping_list)
    db_session.flush()
    assert shopping_list.id is not None and listed.id is not None
    db_session.add(make_shopping_list_item(shopping_list.id, listed.id))
    db_session.flush()

    report = RematchService(db_session).run([PHONE], apply=True)

    assert report.orphans_kept == [listed.id]
    assert db_session.get(Product, listed.id) is not None
    assert owner_of(db_session, moved) == keep.id
    assert RematchService(db_session).run([PHONE], apply=True).orphans_kept == []


def test_rematch_of_phones_with_odd_titles_does_not_raise_and_is_stable(
    db_session: Session,
) -> None:
    owner = product(db_session, PHONE, brand="Unknown", canonical_name="x", specs={})
    for n, title in enumerate(
        ["Điện thoại", "ĐTDĐ", "128GB", "5G", "x" * 5000, "Điện thoại Mock 8GB/128GB", "🔥"]
    ):
        offer(db_session, owner, title, site=SiteKey.nguyenkim, url=f"https://nk.example/p/{n}")
    RematchService(db_session).run([PHONE], apply=True)
    after = snapshot(db_session)
    assert not RematchService(db_session).run([PHONE], apply=True).changed
    assert snapshot(db_session) == after
