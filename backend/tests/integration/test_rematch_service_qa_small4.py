"""QA small-fixes-4: `RematchService` (T5.4b): dữ liệu lệch, nhiều tham chiếu, dữ liệu ngẫu nhiên.

Test `xfail(strict=True)` mã `BUG-S4-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail. Dữ liệu hư cấu, chạy trên test DB (rollback).
"""

import dataclasses
import random
import unicodedata
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, col, select

from app.db.models import (
    Offer,
    PriceAlert,
    PriceHistory,
    Product,
    ShoppingList,
    ShoppingListItem,
)
from app.domain.enums import AlertStatus, Category, SiteKey
from app.normalize.brand import detect_brand
from app.services.rematch_service import REMATCH_CATEGORIES, RematchReport, RematchService
from tests.factories import (
    make_price_alert,
    make_price_history,
    make_shopping_list,
    make_shopping_list_item,
)
from tests.integration.test_rematch_service import (
    ACER,
    ACER_FPT,
    offer,
    owner_of,
    product,
    split_pulsar,
)

TABLES: tuple[type[SQLModel], ...] = (
    Product,
    Offer,
    PriceHistory,
    ShoppingList,
    ShoppingListItem,
    PriceAlert,
)
ACER_OTHER_CODE = ACER.replace("AL15-53P-56QH", "AL15-99X-1234")


def dump(session: Session) -> dict[str, list[dict[str, Any]]]:
    """Toàn bộ các bảng liên quan đọc lại từ CSDL (bỏ cache của session)."""
    session.expire_all()
    return {
        table.__name__: [
            row.model_dump()
            for row in session.exec(select(table).order_by(col(table.id))).all()  # type: ignore[attr-defined]
        ]
        for table in TABLES
    }


def add_list_item(session: Session, product_id: int, **overrides: Any) -> ShoppingListItem:
    shopping_list = make_shopping_list()
    session.add(shopping_list)
    session.flush()
    assert shopping_list.id is not None
    item = make_shopping_list_item(shopping_list.id, product_id, **overrides)
    session.add(item)
    session.flush()
    return item


# ---- chạy thử ----
def test_dry_run_changes_no_table_at_all_on_a_complex_data_set(db_session: Session) -> None:
    wrong, right, red, _black = split_pulsar(db_session)
    assert wrong.id is not None and right.id is not None
    db_session.add(make_price_history(red.id or 0))
    db_session.add(make_price_alert(right.id, status=AlertStatus.paused))
    add_list_item(db_session, right.id, preferred_offer_id=None)
    swap_a = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer A",
        model_code="AL15-99X-1234",
    )
    swap_b = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer B",
        model_code="AL15-53P-56QH",
    )
    offer(db_session, swap_a, ACER)
    offer(db_session, swap_b, ACER_OTHER_CODE, is_active=False)
    db_session.flush()
    before = dump(db_session)

    report = RematchService(db_session).run()

    assert report.changed
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert dump(db_session) == before


# ---- sản phẩm mồ côi ----
def test_every_orphan_is_deleted_unless_a_list_item_or_an_alert_of_any_status_holds_it(
    db_session: Session,
) -> None:
    target = product(db_session, brand="Pulsar", canonical_name="Pulsar X2")
    offer(db_session, target, "Chuột Pulsar X2 Red")
    colours = ["Black", "White", "Blue", "Green", "Pink", "Grey"]
    orphans = [product(db_session, brand="Unknown", canonical_name=f"Pulsar {c}") for c in colours]
    for orphan, colour in zip(orphans, colours, strict=True):
        offer(db_session, orphan, f"Chuột Pulsar X2 {colour}")
    ids = [o.id for o in orphans]
    assert all(i is not None for i in ids)
    db_session.add(make_price_alert(orphans[0].id or 0, status=AlertStatus.active))
    db_session.add(make_price_alert(orphans[1].id or 0, status=AlertStatus.triggered))
    db_session.add(make_price_alert(orphans[2].id or 0, status=AlertStatus.paused))
    add_list_item(db_session, orphans[3].id or 0)
    db_session.flush()

    dry = RematchService(db_session).run([Category.mouse])
    report = RematchService(db_session).run([Category.mouse], apply=True)

    assert report.orphans_kept == ids[:4]
    assert report.products_deleted == ids[4:]
    assert (
        dry.orphans_kept == report.orphans_kept and dry.products_deleted == report.products_deleted
    )
    for pid in ids[:4]:
        assert db_session.get(Product, pid) is not None
    for pid in ids[4:]:
        assert db_session.get(Product, pid) is None
    # Cảnh báo/mục danh sách của sản phẩm bị giữ còn nguyên.
    alerts = db_session.exec(select(PriceAlert.status).order_by(col(PriceAlert.id))).all()
    assert [str(a) for a in alerts] == ["active", "triggered", "paused"]


def test_kept_orphans_do_not_come_back_in_the_next_report(db_session: Session) -> None:
    _wrong, right, _red, _black = split_pulsar(db_session)
    db_session.add(make_price_alert(right.id or 0))
    db_session.flush()

    first = RematchService(db_session).run([Category.mouse], apply=True)
    second = RematchService(db_session).run([Category.mouse], apply=True)

    assert first.orphans_kept == [right.id]
    assert second.orphans_kept == [] and not second.changed


# ---- mã model ----
def test_two_laptop_products_can_swap_their_model_codes_without_a_unique_index_clash(
    db_session: Session,
) -> None:
    first = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer A",
        model_code="AL15-99X-1234",
    )
    second = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer B",
        model_code="AL15-53P-56QH",
    )
    on_first = offer(db_session, first, ACER)  # tiêu đề nói mã 53P
    on_second = offer(db_session, second, ACER_OTHER_CODE)  # tiêu đề nói mã 99X

    report = RematchService(db_session).run([Category.laptop], apply=True)

    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.model_code, second.model_code) == ("AL15-53P-56QH", "AL15-99X-1234")
    assert owner_of(db_session, on_first) == first.id
    assert owner_of(db_session, on_second) == second.id
    assert report.moves == [] and report.products_created == 0
    assert not RematchService(db_session).run([Category.laptop], apply=True).changed


def test_a_product_whose_model_code_changes_does_not_keep_a_name_that_carries_the_old_code(
    db_session: Session,
) -> None:
    first = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer Aspire Lite 15 AL15-99X-1234",
        model_code="AL15-99X-1234",
    )
    offer(db_session, first, ACER)  # offer duy nhất nói mã là AL15-53P-56QH

    RematchService(db_session).run([Category.laptop], apply=True)

    db_session.refresh(first)
    assert first.model_code == "AL15-53P-56QH"
    assert first.canonical_name == "Acer Aspire Lite 15 AL15-53P-56QH"


def test_one_strong_code_under_two_brands_becomes_two_products(db_session: Session) -> None:
    both = product(db_session, Category.laptop, brand="Acer", canonical_name="Acer Mock")
    acer = offer(db_session, both, ACER)
    asus = offer(db_session, both, ACER.replace("Laptop Acer", "Laptop ASUS"))

    report = RematchService(db_session).run([Category.laptop], apply=True)

    assert owner_of(db_session, acer) == both.id
    other = db_session.get(Product, owner_of(db_session, asus))
    assert other is not None and other.id != both.id
    assert (other.brand, other.model_code) == ("ASUS", "AL15-53P-56QH")
    db_session.refresh(both)
    assert (both.brand, both.model_code) == ("Acer", "AL15-53P-56QH")
    assert report.products_created == 1


# ---- offer đã tắt, phạm vi, nhóm ----
def test_inactive_offers_are_rematched_and_stay_inactive_and_keep_their_product_alive(
    db_session: Session,
) -> None:
    only = product(db_session, brand="Unknown", canonical_name="Chuột Pulsar X2 Red")
    dead = offer(db_session, only, "Chuột Pulsar X2 Red", is_active=False)
    right = product(db_session, brand="Pulsar", canonical_name="Pulsar X2")
    live = offer(db_session, right, "Chuột Pulsar X2 Black")

    report = RematchService(db_session).run([Category.mouse], apply=True)

    assert report.offers_checked == 2
    assert owner_of(db_session, dead) == owner_of(db_session, live) == only.id
    db_session.refresh(dead)
    assert dead.is_active is False
    assert db_session.get(Product, right.id) is None


def test_a_product_with_only_inactive_offers_is_not_deleted(db_session: Session) -> None:
    only = product(db_session, brand="Pulsar", canonical_name="Pulsar X2")
    offer(db_session, only, "Chuột Pulsar X2 Red", is_active=False)

    report = RematchService(db_session).run([Category.mouse], apply=True)

    assert report.products_deleted == [] and not report.changed
    assert db_session.get(Product, only.id) is not None


def test_site_filter_leaves_a_product_spanning_two_sites_intact_and_splits_the_scoped_offer(
    db_session: Session,
) -> None:
    both = product(db_session, brand="Unknown", canonical_name="Chuột Pulsar X2 Red")
    fpt = offer(db_session, both, "Chuột Pulsar X2 Red", site=SiteKey.fptshop)
    gearvn = offer(db_session, both, "Chuột Pulsar X2 Black")

    scoped = RematchService(db_session).run([Category.mouse], site=SiteKey.gearvn, apply=True)

    assert (both.brand, both.canonical_name) == ("Unknown", "Chuột Pulsar X2 Red")
    assert owner_of(db_session, fpt) == both.id
    new_owner = owner_of(db_session, gearvn)
    assert new_owner != both.id
    split = db_session.get(Product, new_owner)
    assert split is not None and split.brand == "Pulsar"
    assert scoped.products_created == 1 and scoped.products_deleted == []
    assert (
        not RematchService(db_session)
        .run([Category.mouse], site=SiteKey.gearvn, apply=True)
        .changed
    )

    # Chạy đủ mọi trang sau đó gộp lại thành một sản phẩm và xóa bản thừa.
    full = RematchService(db_session).run([Category.mouse], apply=True)
    assert owner_of(db_session, fpt) == owner_of(db_session, gearvn) == both.id
    assert full.products_deleted == [new_owner]


def test_rematching_one_category_never_touches_products_of_another(db_session: Session) -> None:
    laptop = product(db_session, Category.laptop, brand="Unknown", canonical_name="Laptop lạ")
    offer(db_session, laptop, ACER)
    split_pulsar(db_session)
    laptop_before = laptop.model_dump()

    RematchService(db_session).run([Category.mouse], apply=True)

    db_session.refresh(laptop)
    assert laptop.model_dump() == laptop_before


def test_a_category_without_offers_reports_nothing_and_changes_nothing(
    db_session: Session,
) -> None:
    lonely = product(db_session, Category.keyboard, brand="Akko", canonical_name="Akko 3068")
    before = dump(db_session)

    report = RematchService(db_session).run([Category.keyboard], apply=True)

    assert report == RematchReport(applied=True)
    assert not report.changed and report.offers_checked == 0
    assert dump(db_session) == before
    assert db_session.get(Product, lonely.id) is not None


@pytest.mark.parametrize("category", [Category.phone, Category.other])
def test_categories_without_an_extractor_run_without_error_and_are_idempotent(
    db_session: Session, category: Category
) -> None:
    first = product(db_session, category, brand="Apple", canonical_name="iPhone 15 128GB")
    offer(db_session, first, "iPhone 15 128GB Black")
    offer(db_session, first, "iPhone 15 128GB White")

    RematchService(db_session).run([category], apply=True)
    before = dump(db_session)
    again = RematchService(db_session).run([category], apply=True)

    assert not again.changed
    assert dump(db_session) == before


# ---- dữ liệu lạ ----
def test_empty_very_long_and_decomposed_titles_do_not_break_the_run(db_session: Session) -> None:
    host = product(db_session, brand="Unknown", canonical_name="x")
    offer(db_session, host, "")
    offer(db_session, host, "Chuột Logitech G304 " + "x" * 50_000)
    composed = offer(db_session, host, "Chuột Logitech G304 Đen")
    decomposed = offer(db_session, host, unicodedata.normalize("NFD", "Chuột Logitech G304 Trắng"))

    RematchService(db_session).run([Category.mouse], apply=True)
    before = dump(db_session)
    again = RematchService(db_session).run([Category.mouse], apply=True)

    assert not again.changed
    assert dump(db_session) == before
    # NFC và NFD của cùng một tiêu đề phải ra cùng một mẫu.
    assert owner_of(db_session, composed) == owner_of(db_session, decomposed)


@pytest.mark.xfail(
    strict=True,
    reason="BUG-S4-4: raw_specs có giá trị không phải chuỗi làm cả lượt ghép lại ném TypeError",
)
@pytest.mark.parametrize("value", [16, None, ["16 GB"], True])
def test_an_offer_with_a_non_string_raw_spec_value_does_not_abort_the_whole_run(
    db_session: Session, value: object
) -> None:
    host = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer Aspire Lite 15 AL15-53P-56QH",
    )
    offer(db_session, host, ACER, raw_specs={"Dung lượng RAM": value})
    offer(db_session, host, ACER_FPT)

    report = RematchService(db_session).run([Category.laptop], apply=True)

    assert report.offers_checked == 2


# ---- tham chiếu từ danh sách mua / lịch sử giá ----
def test_price_history_and_ids_of_moved_offers_are_preserved(db_session: Session) -> None:
    _wrong, right, _red, black = split_pulsar(db_session)
    assert black.id is not None
    db_session.add(make_price_history(black.id, price=1_111_000))
    db_session.add(make_price_history(black.id, price=999_000))
    db_session.flush()

    RematchService(db_session).run([Category.mouse], apply=True)

    prices = db_session.exec(
        select(PriceHistory.price)
        .where(PriceHistory.offer_id == black.id)
        .order_by(col(PriceHistory.id))
    ).all()
    assert list(prices) == [1_111_000, 999_000]
    assert db_session.get(Offer, black.id) is not None
    assert db_session.get(Product, right.id) is None


def test_a_list_item_never_prefers_an_offer_that_moved_to_another_product(
    db_session: Session,
) -> None:
    # ShoppingListRepository chỉ cho `preferred_offer_id` là offer của chính sản phẩm của mục.
    wrong, right, _red, black = split_pulsar(db_session)
    assert right.id is not None and wrong.id is not None
    item = add_list_item(db_session, right.id, preferred_offer_id=black.id)

    RematchService(db_session).run([Category.mouse], apply=True)

    db_session.refresh(item)
    if item.preferred_offer_id is not None:
        owner = db_session.get(Offer, item.preferred_offer_id)
        assert owner is not None and owner.product_id == item.product_id


# ---- tính chất trên dữ liệu ngẫu nhiên (seed cố định) ----
BRANDS = ["Unknown", "Logitech", "Pulsar", "Razer", "Acer", "ASUS", "Sony", "HyperX", "Akko"]
TITLES: dict[Category, list[str]] = {
    Category.mouse: [
        "Chuột Logitech G304 Black",
        "Chuột Logitech G304 White",
        "Chuột không dây Logitech G304 Lightspeed",
        "Logitech MX Master 3S",
        "Chuột không dây Logitech MX Master 3S Graphite",
        "Chuột Pulsar X2 Red",
        "Chuột Pulsar X2 Mini Black",
        "Pulsar X2 Mini",
        "Chuột gaming Razer DeathAdder V3",
        "Razer DeathAdder V3 Pro",
        "Chuột lạ không rõ hãng",
        "[Hot] Chuột Dell MS116 (Mới 100%)",
        "Chuột Dell MS116 USB",
    ],
    Category.keyboard: [
        "Bàn phím cơ Akko 3068 Gateron Reaper switch",
        "Bàn phím cơ AKKO 3068 - Reaper switch",
        "Bàn phím Akko 3068B Plus",
        "Bàn phím Logitech K380 Bluetooth",
        "Logitech K380",
        "Bàn phím cơ Keychron K2 Pro 75%",
        "Bàn phím cơ không dây Keychron K2 Pro",
        "Bàn phím lạ",
    ],
    Category.headset: [
        "Tai nghe chụp tai Sony WH-1000XM5",
        "Sony WH-1000XM5 Black",
        "Tai nghe HyperX Cloud II",
        "Tai nghe HyperX Cloud II Wireless",
        "Tai nghe gaming Razer Kraken V3",
        "Tai nghe không rõ hãng",
    ],
    Category.laptop: [
        ACER,
        ACER_FPT,
        ACER_OTHER_CODE,
        ACER.replace("8GB", "16GB"),
        "Laptop ASUS TUF Gaming F16 FX608JHR-RV003W (i7-14650HX/16GB/512GB/RTX 5060)",
        "Laptop ASUS TUF Gaming F16 FX608 i7-14650HX 16GB 512GB RTX 5060",
        "Laptop Lenovo LOQ 15IRX9 83DV01MCVN i5-13450HX/16GB/512GB/RTX 4050",
        "Laptop HP 15-fd0233TU 8D737PA i5-1334U/16GB/512GB",
        "Laptop Dell Inspiron 15 3520 i5-1235U 8GB 512GB",
        "Laptop lạ không rõ",
    ],
}
RAW_POOL: list[dict[str, str]] = [
    {},
    {"Ghi chú": "x"},
    {"Dung lượng RAM": "16 GB"},
    {"Card đồ họa": "NVIDIA GeForce RTX 4050 6GB"},
    {"Kết nối": "Không dây 2.4GHz"},
    {"Switch": "Gateron Red"},
    {"CPU": "Intel Core i5"},
]
SPECS_POOL: list[dict[str, Any]] = [
    {},
    {"ram_gb": 16},
    {"connection": ["wired"]},
    {"foo": 1},
    {"cpu_model": "Intel Core i5"},
    {"ram_gb": "8"},
]
CODES = ["AL15-53P-56QH", "AL15-99X-1234", "MOCK-ASUS-TUF16", None, "FX608", None]


def build_world(session: Session, category: Category, seed: int) -> None:
    rng = random.Random(seed)
    products: list[Product] = []
    used: set[tuple[str, str]] = set()
    for _ in range(rng.randint(2, 5)):
        brand = rng.choice(BRANDS)
        code = rng.choice(CODES) if category is Category.laptop else None
        if code is not None and (brand, code) in used:
            code = None
        if code is not None:
            used.add((brand, code))
        products.append(
            product(
                session,
                category,
                brand=brand,
                canonical_name=f"{brand} mock {len(products)}",
                model_code=code,
                specs=rng.choice(SPECS_POOL),
            )
        )
    shopping_list = make_shopping_list()
    session.add(shopping_list)
    session.flush()
    for held in products:
        assert held.id is not None
        for _ in range(rng.randint(0, 3)):
            title = rng.choice(TITLES[category])
            roll = rng.random()
            if roll < 0.05:
                title = ""
            elif roll < 0.12:
                title = unicodedata.normalize("NFD", title)
            row = offer(
                session,
                held,
                title,
                site=rng.choice([SiteKey.gearvn, SiteKey.fptshop, SiteKey.anphat]),
                is_active=rng.random() < 0.8,
                raw_specs=rng.choice(RAW_POOL),
                price=rng.randint(100_000, 50_000_000),
            )
            assert row.id is not None
            session.add(make_price_history(row.id, price=row.price))
        if rng.random() < 0.25:
            session.add(make_price_alert(held.id, status=rng.choice(list(AlertStatus))))
        if rng.random() < 0.25:
            session.add(make_shopping_list_item(shopping_list.id or 0, held.id))
    session.flush()


# Seed làm lượt `--apply` đầu để lại sản phẩm trùng (BUG-S4-6); các seed khác đều idempotent.
NOT_IDEMPOTENT_SEEDS = {(Category.keyboard, 1), (Category.mouse, 47)}


def comparable(rows: list[dict[str, Any]], drop: set[str]) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k not in drop} for row in rows]


@pytest.mark.parametrize(
    "category", [Category.mouse, Category.keyboard, Category.headset, Category.laptop]
)
def test_on_random_data_dry_run_matches_apply_and_apply_keeps_every_invariant_and_is_idempotent(
    db_session: Session, category: Category
) -> None:
    for seed in range(50):
        with db_session.begin_nested() as savepoint:
            build_world(db_session, category, seed)
            before = dump(db_session)

            dry = RematchService(db_session).run([category])
            assert dump(db_session) == before, f"seed {seed}: dry run wrote to the DB"
            applied = RematchService(db_session).run([category], apply=True)
            assert dataclasses.replace(dry, applied=True) == applied, f"seed {seed}"

            after = dump(db_session)
            # Offer: không mất, không đổi gì ngoài chủ sở hữu/cách ghép.
            moved = {"product_id", "match_method", "match_score"}
            assert comparable(after["Offer"], moved) == comparable(before["Offer"], moved), seed
            assert after["PriceHistory"] == before["PriceHistory"], seed
            assert after["ShoppingListItem"] == before["ShoppingListItem"], seed
            assert after["PriceAlert"] == before["PriceAlert"], seed
            # Mọi offer nằm ở sản phẩm đúng hãng với tiêu đề của nó.
            for row in db_session.exec(select(Offer)).all():
                owner = db_session.get(Product, row.product_id)
                assert owner is not None and owner.category is category
                assert owner.brand == detect_brand(row.title), (seed, row.title)
            # Sản phẩm có offer trước đó giờ hoặc còn offer, hoặc còn được tham chiếu.
            had_offers = {r["product_id"] for r in before["Offer"]}
            has_offers = {r["product_id"] for r in after["Offer"]}
            referenced = {r["product_id"] for r in after["ShoppingListItem"]} | {
                r["product_id"] for r in after["PriceAlert"]
            }
            alive = {r["id"] for r in after["Product"]}
            assert had_offers - has_offers - referenced <= set(applied.products_deleted)
            assert not (set(applied.products_deleted) & alive), seed
            assert set(applied.orphans_kept) <= alive and set(applied.orphans_kept) <= referenced

            if (category, seed) not in NOT_IDEMPOTENT_SEEDS:
                again = RematchService(db_session).run([category], apply=True)
                assert not again.changed, (seed, again)
                assert dump(db_session) == after, f"seed {seed}: second run changed the DB"
            savepoint.rollback()


@pytest.mark.parametrize(("category", "seed"), sorted(NOT_IDEMPOTENT_SEEDS))
def test_second_run_changes_nothing_on_seeds_that_expose_the_polluted_specs_bug(
    db_session: Session, category: Category, seed: int
) -> None:
    build_world(db_session, category, seed)
    RematchService(db_session).run([category], apply=True)
    after = dump(db_session)

    again = RematchService(db_session).run([category], apply=True)

    assert not again.changed
    assert dump(db_session) == after


def test_an_offer_leaving_its_product_does_not_carry_that_products_specs_into_matching(
    db_session: Session,
) -> None:
    # `own.specs` (kết nối "có dây" của chuột Razer) bị trộn vào offer Dell vốn thuộc chuột khác,
    # nên offer Dell thứ hai bị coi là mâu thuẫn với offer Dell thứ nhất (không dây) và tách riêng.
    dell_host = product(db_session, brand="Akko", canonical_name="Akko mock 1")
    razer_host = product(
        db_session, brand="ASUS", canonical_name="ASUS mock 2", specs={"connection": ["wired"]}
    )
    dell = "[Hot] Chuột Dell MS116 (Mới 100%)"
    first = offer(db_session, dell_host, dell, raw_specs={"Kết nối": "Không dây 2.4GHz"})
    offer(db_session, razer_host, "Chuột gaming Razer DeathAdder V3")
    second = offer(db_session, razer_host, dell)

    RematchService(db_session).run([Category.mouse], apply=True)

    assert owner_of(db_session, first) == owner_of(db_session, second)


def test_full_default_run_over_every_category_is_idempotent(db_session: Session) -> None:
    for seed, category in enumerate(REMATCH_CATEGORIES):
        build_world(db_session, category, 100 + seed)

    first = RematchService(db_session).run(apply=True)
    after = dump(db_session)
    second = RematchService(db_session).run(apply=True)

    assert first.offers_checked == second.offers_checked
    assert not second.changed
    assert dump(db_session) == after
