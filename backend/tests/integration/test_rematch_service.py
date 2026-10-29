"""Ghép lại offer đã có (`RematchService`, T5.4): chuyển offer, tách/gộp sản phẩm, dựng lại specs,
xóa sản phẩm mồ côi không bị tham chiếu. Dữ liệu hư cấu, chạy trên test DB (rollback)."""

from typing import Any

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer, Product
from app.db.repositories import ProductRepository
from app.domain.enums import Category, MatchMethod, SiteKey
from app.services.rematch_service import RematchService
from tests.factories import (
    make_offer,
    make_price_alert,
    make_product,
    make_shopping_list,
    make_shopping_list_item,
)

ACER = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'
ACER_FPT = "Laptop Acer Aspire Lite 15 AL15-53P-56QH Core 5 120U/8GB/512GB"


def product(session: Session, category: Category = Category.mouse, **overrides: Any) -> Product:
    defaults: dict[str, Any] = {"category": category, "model_code": None, "specs": {}}
    return ProductRepository(session).add(make_product(**{**defaults, **overrides}))


def offer(session: Session, owner: Product, title: str, **overrides: Any) -> Offer:
    assert owner.id is not None
    row = make_offer(owner.id, **{"title": title, "site": SiteKey.gearvn, **overrides})
    session.add(row)
    session.flush()
    return row


def owner_of(session: Session, row: Offer) -> int:
    session.refresh(row)
    return row.product_id


def snapshot(session: Session) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    offers = session.exec(select(Offer.id, Offer.product_id).order_by(col(Offer.id))).all()
    products = session.exec(
        select(Product.id, Product.brand, Product.canonical_name, Product.model_code).order_by(
            col(Product.id)
        )
    ).all()
    return [tuple(o) for o in offers], [tuple(p) for p in products]


def split_pulsar(session: Session) -> tuple[Product, Product, Offer, Offer]:
    """Một mẫu bị ghép nhầm thành hai sản phẩm (hãng cũ `Unknown`); offer đầu ở bản sai hãng."""
    wrong = product(session, brand="Unknown", canonical_name="Chuột Pulsar X2 Red")
    right = product(session, brand="Pulsar", canonical_name="Pulsar X2")
    red = offer(session, wrong, "Chuột Pulsar X2 Red")
    black = offer(session, right, "Chuột Pulsar X2 Black")
    return wrong, right, red, black


def test_offers_of_one_model_are_merged_and_the_unreferenced_orphan_is_deleted(
    db_session: Session,
) -> None:
    wrong, right, red, black = split_pulsar(db_session)
    assert wrong.id is not None and right.id is not None

    report = RematchService(db_session).run([Category.mouse], apply=True)

    # Offer đầu (id nhỏ) giữ sản phẩm của nó, được sửa hãng và tên chuẩn.
    assert owner_of(db_session, red) == wrong.id
    assert owner_of(db_session, black) == wrong.id
    db_session.refresh(wrong)
    assert (wrong.brand, wrong.canonical_name) == ("Pulsar", "Pulsar X2")
    assert db_session.get(Product, right.id) is None
    assert report.products_deleted == [right.id]
    assert report.products_renamed == [wrong.id]
    assert [(m.offer_id, m.from_product_id, m.to_product_id) for m in report.moves] == [
        (black.id, right.id, wrong.id)
    ]
    assert report.moves[0].method is MatchMethod.fuzzy
    db_session.refresh(black)
    assert black.match_method is MatchMethod.fuzzy


@pytest.mark.parametrize("reference", ["shopping_list", "price_alert"])
def test_an_orphan_still_in_a_shopping_list_or_alert_is_kept_and_reported(
    db_session: Session, reference: str
) -> None:
    _wrong, right, _red, black = split_pulsar(db_session)
    assert right.id is not None
    if reference == "shopping_list":
        shopping_list = make_shopping_list()
        db_session.add(shopping_list)
        db_session.flush()
        assert shopping_list.id is not None
        db_session.add(make_shopping_list_item(shopping_list.id, right.id))
    else:
        db_session.add(make_price_alert(right.id))
    db_session.flush()

    dry = RematchService(db_session).run([Category.mouse])
    report = RematchService(db_session).run([Category.mouse], apply=True)

    assert dry.orphans_kept == report.orphans_kept == [right.id]
    assert dry.products_deleted == report.products_deleted == []
    assert db_session.get(Product, right.id) is not None
    assert owner_of(db_session, black) != right.id


def test_dry_run_reports_the_same_changes_without_writing_anything(db_session: Session) -> None:
    wrong, right, _red, black = split_pulsar(db_session)
    before = snapshot(db_session)

    report = RematchService(db_session).run([Category.mouse])

    assert snapshot(db_session) == before
    assert report.applied is False
    assert [(m.offer_id, m.to_product_id) for m in report.moves] == [(black.id, wrong.id)]
    assert report.products_deleted == [right.id]
    assert report.changed


def test_running_twice_changes_nothing_the_second_time(db_session: Session) -> None:
    split_pulsar(db_session)
    first = RematchService(db_session).run([Category.mouse], apply=True)
    before = snapshot(db_session)

    second = RematchService(db_session).run([Category.mouse], apply=True)

    assert first.changed
    assert not second.changed
    assert second.offers_checked == first.offers_checked == 2
    assert snapshot(db_session) == before


def test_a_product_holding_two_models_is_split(db_session: Session) -> None:
    both = product(db_session, brand="Pulsar", canonical_name="Pulsar X2")
    x2 = offer(db_session, both, "Chuột Pulsar X2 Black")
    mini = offer(db_session, both, "Chuột Pulsar X2 Mini Black")

    report = RematchService(db_session).run([Category.mouse], apply=True)

    assert owner_of(db_session, x2) == both.id
    new_owner = owner_of(db_session, mini)
    assert new_owner != both.id
    split = db_session.get(Product, new_owner)
    assert split is not None and (split.brand, split.canonical_name) == ("Pulsar", "Pulsar X2 Mini")
    assert report.products_created == 1
    assert [(m.offer_id, m.to_product_id, m.method) for m in report.moves] == [
        (mini.id, None, MatchMethod.new)
    ]
    db_session.refresh(mini)
    assert (mini.match_method, mini.match_score) == (MatchMethod.new, None)


def test_rebuilt_specs_prefer_the_spec_table_over_titles(db_session: Session) -> None:
    laptop = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer Aspire Lite 15 AL15-53P-56QH",
        model_code="AL15-53P-56QH",
        specs={"screen_in": 15.6, "ram_gb": 8, "storage_gb": 512, "cpu_model": "Core 5 120U"},
    )
    offer(db_session, laptop, ACER)  # tiêu đề ghi 15.6"
    offer(db_session, laptop, ACER_FPT, raw_specs={"Kích thước màn hình": "16 inch"})

    report = RematchService(db_session).run([Category.laptop], apply=True)

    db_session.refresh(laptop)
    assert report.moves == []
    assert laptop.specs["screen_in"] == 16.0  # nhãn của offer sau thắng tiêu đề của offer đầu
    assert laptop.specs["ram_gb"] == 8
    assert report.products_specs_changed == [laptop.id]


def test_rebuilt_specs_keep_old_values_that_titles_cannot_overrule(db_session: Session) -> None:
    # Specs cũ (seed, LLM dự phòng) chi tiết hơn tiêu đề: tiêu đề chỉ bù trường còn trống.
    laptop = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer Aspire Lite 15 AL15-53P-56QH",
        model_code="AL15-53P-56QH",
        specs={"gpu_model": "Integrated", "ram_gb": 32},
    )
    offer(db_session, laptop, ACER)

    RematchService(db_session).run([Category.laptop], apply=True)

    db_session.refresh(laptop)
    assert laptop.specs["gpu_model"] == "Integrated"
    assert laptop.specs["ram_gb"] == 32  # tiêu đề ghi 8GB nhưng không thắng giá trị cũ
    assert laptop.specs["storage_gb"] == 512  # trường trống được tiêu đề bù


def test_rebuilt_specs_let_a_spec_table_value_replace_an_old_value(db_session: Session) -> None:
    laptop = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer Aspire Lite 15 AL15-53P-56QH",
        model_code="AL15-53P-56QH",
        specs={"ram_gb": 8},
    )
    offer(db_session, laptop, ACER, raw_specs={"Dung lượng RAM": "16 GB"})

    RematchService(db_session).run([Category.laptop], apply=True)

    db_session.refresh(laptop)
    assert laptop.specs["ram_gb"] == 16


def test_a_duplicate_product_holding_the_model_code_hands_it_over(db_session: Session) -> None:
    # Hai sản phẩm của cùng một mã (lỗi cũ); sản phẩm của offer đầu chưa có mã, bản trùng giữ mã.
    first = product(db_session, Category.laptop, brand="Acer", canonical_name="Acer Aspire Lite 15")
    duplicate = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer Aspire Lite 15 AL15-53P-56QH",
        model_code="AL15-53P-56QH",
    )
    offer(db_session, first, ACER)
    moved = offer(db_session, duplicate, ACER_FPT)

    report = RematchService(db_session).run([Category.laptop], apply=True)

    db_session.refresh(first)
    assert first.model_code == "AL15-53P-56QH"
    assert owner_of(db_session, moved) == first.id
    assert report.products_deleted == [duplicate.id]


def test_site_filter_only_rematches_offers_of_that_site(db_session: Session) -> None:
    wrong = product(db_session, brand="Unknown", canonical_name="Chuột Pulsar X2 Red")
    right = product(db_session, brand="Pulsar", canonical_name="Pulsar X2")
    fpt = offer(db_session, wrong, "Chuột Pulsar X2 Red", site=SiteKey.fptshop)
    gearvn = offer(db_session, right, "Chuột Pulsar X2 Black")
    other = offer(db_session, wrong, "Chuột Pulsar X2 White")  # gearvn, đang ở sản phẩm sai

    report = RematchService(db_session).run([Category.mouse], site=SiteKey.gearvn, apply=True)

    assert report.offers_checked == 2
    assert owner_of(db_session, fpt) == wrong.id  # offer ngoài phạm vi không bị đụng
    assert owner_of(db_session, gearvn) == right.id
    assert owner_of(db_session, other) == right.id  # ghép vào sản phẩm đúng hãng
    db_session.refresh(wrong)
    assert wrong.brand == "Unknown"  # sản phẩm còn offer ngoài phạm vi giữ nguyên
    assert report.products_deleted == []


def test_offers_without_specs_stay_with_their_product_through_its_code_and_specs(
    db_session: Session,
) -> None:
    # Chạy thử trên DB dev: offer seed không có `raw_specs`, tiêu đề chỉ có mã yếu dùng chung
    # ("FX608"); trước khi dùng mã + specs của sản phẩm hiện tại, offer thứ hai bị tách ra.
    specs = {"cpu_model": "i7-14650HX", "gpu_model": "RTX 5060", "ram_gb": 16, "storage_gb": 1024}
    other = product(
        db_session,
        Category.laptop,
        brand="ASUS",
        canonical_name="ASUS Mock TUF Gaming F16 FX608",
        model_code="MOCK-ASUS-TUF16",
        specs={**specs, "gpu_model": "RTX 4060"},
    )
    seeded = product(
        db_session,
        Category.laptop,
        brand="ASUS",
        canonical_name="ASUS Mock TUF Gaming F16 FX608 RTX 5060",
        model_code="MOCK-ASUS-TUF5060",
        specs=specs,
    )
    title = "ASUS Mock TUF Gaming F16 FX608 RTX 5060 - Chính hãng"
    offer(db_session, other, "ASUS Mock TUF Gaming F16 FX608 - Chính hãng")
    gearvn = offer(db_session, seeded, title)
    fpt = offer(db_session, seeded, title, site=SiteKey.fptshop)

    report = RematchService(db_session).run([Category.laptop], apply=True)

    assert owner_of(db_session, gearvn) == owner_of(db_session, fpt) == seeded.id
    db_session.refresh(seeded)
    assert seeded.model_code == "MOCK-ASUS-TUF5060"  # mã đang có thắng mã yếu trong tên
    assert seeded.canonical_name == "ASUS Mock TUF Gaming F16 FX608 RTX 5060"  # hãng không đổi
    assert report.moves == [] and report.products_created == 0


def test_more_detailed_old_values_are_not_overruled_by_a_title(db_session: Session) -> None:
    # Chạy thử trên DB dev: seed ghi kết nối [2.4G, Bluetooth], tiêu đề chỉ nói "không dây".
    mouse = product(
        db_session,
        brand="Logitech",
        canonical_name="Logitech MX Master 3S",
        specs={"connection": ["wireless_2_4", "bluetooth"]},
    )
    offer(db_session, mouse, "Chuột không dây Logitech MX Master 3S")

    report = RematchService(db_session).run([Category.mouse], apply=True)

    db_session.refresh(mouse)
    assert mouse.specs["connection"] == ["wireless_2_4", "bluetooth"]
    assert report.products_specs_changed == []
