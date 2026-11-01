"""resolve_product và repository hỗ trợ ghép (T5.2): PostgreSQL thật."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.models import Product
from app.db.repositories import OfferRepository, OfferUpsert, ProductRepository
from app.domain.dto import ListingItem, ProductDetail
from app.domain.enums import Category, MatchMethod, SiteKey
from app.scrapers.pipeline import Resolution, find_existing_offer, resolve_product

ACER = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'
ACER_FPT = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH Core 5 120U/8GB/512GB/15.6" FHD/Win11'


def item(
    title: str, site: SiteKey = SiteKey.gearvn, slug: str = "a", **raw_specs: str
) -> ListingItem:
    return ListingItem(
        site=site,
        url=f"https://{site.value}.example/p/{slug}",
        title=title,
        price=1_000_000,
        raw_specs=raw_specs,
    )


def store(session: Session, resolution: Resolution, listing: ListingItem) -> None:
    """Ghi offer như pipeline làm sau khi resolver trả `Resolution`."""
    OfferRepository(session).upsert(
        OfferUpsert(
            product_id=resolution.product_id,
            site=listing.site,
            url=str(listing.url),
            title=listing.title,
            price=1_000_000,
            match_method=resolution.method,
            match_score=resolution.score,
        )
    )


def product_of(session: Session, resolution: Resolution) -> Product:
    product = ProductRepository(session).get(resolution.product_id)
    assert product is not None
    return product


def test_new_laptop_gets_canonical_name_model_code_and_method_new(db_session: Session) -> None:
    resolution = resolve_product(db_session, Category.laptop, item(ACER), None)

    assert (resolution.method, resolution.score) == (MatchMethod.new, None)
    product = product_of(db_session, resolution)
    assert (product.brand, product.model_code) == ("Acer", "AL15-53P-56QH")
    assert product.canonical_name == "Acer Aspire Lite 15 AL15-53P-56QH"
    assert product.specs["ram_gb"] == 8


def test_same_model_code_on_another_site_merges_and_fills_missing_specs(
    db_session: Session,
) -> None:
    first = item(ACER, slug="a")
    res_a = resolve_product(db_session, Category.laptop, first, None)
    store(db_session, res_a, first)
    assert "gpu_model" not in product_of(db_session, res_a).specs

    second = item(ACER_FPT, SiteKey.fptshop, "b", **{"Card đồ hoạ": "AMD Radeon 680M Graphics"})
    res_b = resolve_product(db_session, Category.laptop, second, None)

    assert res_b.product_id == res_a.product_id
    assert (res_b.method, res_b.score) == (MatchMethod.model_code, 1.0)
    merged = product_of(db_session, res_b)
    assert merged.specs["gpu_model"] == "Integrated"  # trường thiếu được điền
    assert merged.specs_confidence == 1.0


def test_conflicting_optional_spec_keeps_the_old_value_and_logs_a_warning(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    first = item(ACER, slug="a")
    res_a = resolve_product(db_session, Category.laptop, first, None)
    store(db_session, res_a, first)

    # Cùng mã, trường bắt buộc không mâu thuẫn; độ phân giải (trường phụ) lệch nên chỉ cảnh báo.
    second = item(ACER_FPT.replace("FHD", "WUXGA"), SiteKey.fptshop, "b")
    with caplog.at_level("WARNING"):
        res_b = resolve_product(db_session, Category.laptop, second, None)

    assert res_b.product_id == res_a.product_id
    assert product_of(db_session, res_b).specs["resolution"] == "1920x1080"
    assert "mâu thuẫn" in caplog.text


def test_same_code_with_conflicting_ram_creates_a_product_without_the_code(
    db_session: Session,
) -> None:
    first = item(ACER, slug="a")
    res_a = resolve_product(db_session, Category.laptop, first, None)
    store(db_session, res_a, first)

    second = item(ACER.replace("8GB", "16GB"), slug="b")
    res_b = resolve_product(db_session, Category.laptop, second, None)

    assert res_b.product_id != res_a.product_id and res_b.method is MatchMethod.new
    assert product_of(db_session, res_b).model_code is None
    assert product_of(db_session, res_a).model_code == "AL15-53P-56QH"


def test_accessory_colour_variants_merge_and_other_models_do_not(db_session: Session) -> None:
    red = item("Chuột Pulsar X2 Red", slug="red")
    res_red = resolve_product(db_session, Category.mouse, red, None)
    store(db_session, res_red, red)

    black = item("Chuột Pulsar X2 Black", slug="black")
    res_black = resolve_product(db_session, Category.mouse, black, None)
    mini = item("Chuột Pulsar X2 Mini Black", slug="mini")
    res_mini = resolve_product(db_session, Category.mouse, mini, None)

    assert (res_black.product_id, res_black.method) == (res_red.product_id, MatchMethod.fuzzy)
    assert res_black.score == 1.0
    assert res_mini.product_id != res_red.product_id and res_mini.method is MatchMethod.new
    assert product_of(db_session, res_red).canonical_name == "Pulsar X2"


def test_products_of_other_brands_or_categories_are_never_candidates(db_session: Session) -> None:
    mouse = item("Chuột Pulsar X2 Red", slug="m")
    res_mouse = resolve_product(db_session, Category.mouse, mouse, None)
    store(db_session, res_mouse, mouse)

    other_category = resolve_product(
        db_session, Category.keyboard, item("Bàn phím Pulsar X2", slug="k"), None
    )
    other_brand = resolve_product(
        db_session, Category.mouse, item("Chuột Razer X2", slug="r"), None
    )

    assert other_category.product_id != res_mouse.product_id
    assert other_brand.product_id != res_mouse.product_id


def test_unknown_brand_titles_become_separate_products(db_session: Session) -> None:
    first = item("Chuột Infinity Shadow White", slug="a")
    res_a = resolve_product(db_session, Category.mouse, first, None)
    store(db_session, res_a, first)

    other = item("Chuột Infinity Shadow Black", slug="b")
    res_b = resolve_product(db_session, Category.mouse, other, None)

    assert product_of(db_session, res_a).brand == "Unknown"
    assert res_b.product_id != res_a.product_id


def test_existing_offer_keeps_its_product_and_match_info(db_session: Session) -> None:
    first = item("Chuột Pulsar X2 Red", slug="red")
    store(db_session, resolve_product(db_session, Category.mouse, first, None), first)
    black = item("Chuột Pulsar X2 Black", slug="black")
    res_black = resolve_product(db_session, Category.mouse, black, None)
    store(db_session, res_black, black)

    again = resolve_product(db_session, Category.mouse, black, None)

    assert again == res_black  # cùng sản phẩm, vẫn ghi nhận là "fuzzy" với điểm cũ


def test_offer_with_code_is_a_separate_product_from_a_codeless_one_with_a_different_name(
    db_session: Session,
) -> None:
    no_code = item("Laptop Acer Aspire Lite 15 (Core 5-120U/ 8GB/ 512GB/ Intel Graphics)", slug="a")
    res_a = resolve_product(db_session, Category.laptop, no_code, None)
    store(db_session, res_a, no_code)
    assert product_of(db_session, res_a).model_code is None

    with_code = item(ACER.replace("Win 11", "Intel Graphics"), slug="b")
    res_b = resolve_product(db_session, Category.laptop, with_code, None)

    # Một bên có mã trong tên, bên kia không: tên khác nhau nên không ghép mờ.
    assert res_b.product_id != res_a.product_id
    assert product_of(db_session, res_b).model_code == "AL15-53P-56QH"


def test_model_code_is_assigned_to_a_fuzzy_matched_product_without_code(
    db_session: Session,
) -> None:
    title = 'Laptop Acer Aspire Lite 15 (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'
    gpu = {"Card đồ hoạ": "Intel Graphics"}
    plain = item(title, slug="plain", **gpu)
    res_plain = resolve_product(db_session, Category.laptop, plain, None)
    store(db_session, res_plain, plain)
    detail = ProductDetail(url="https://gearvn.example/p/coded", model_code_hint="MK-LA001")

    res_coded = resolve_product(
        db_session, Category.laptop, item(title, slug="coded", **gpu), detail
    )

    assert res_coded.product_id == res_plain.product_id
    assert res_coded.method is MatchMethod.fuzzy
    assert product_of(db_session, res_coded).model_code == "MK-LA001"


def test_colour_part_numbers_do_not_split_an_accessory(db_session: Session) -> None:
    # T5.4: MPN theo màu không thành mã model của phụ kiện nên hai màu vẫn là một sản phẩm.
    red = item("Chuột Pulsar X2 Red", slug="red")
    res_red = resolve_product(
        db_session,
        Category.mouse,
        red,
        ProductDetail(url="https://gearvn.example/p/red", model_code_hint="PX2-RED"),
    )
    store(db_session, res_red, red)

    res_black = resolve_product(
        db_session,
        Category.mouse,
        item("Chuột Pulsar X2 Black", slug="black"),
        ProductDetail(url="https://gearvn.example/p/black", model_code_hint="PX2-BLK"),
    )

    assert res_black.product_id == res_red.product_id
    assert product_of(db_session, res_black).model_code is None


def test_hint_code_from_the_detail_page_is_used(db_session: Session) -> None:
    detail = ProductDetail(url="https://gearvn.example/p/a", model_code_hint="mk-la001")

    resolution = resolve_product(
        db_session, Category.laptop, item("Laptop ASUS Mock Strix 15 X01"), detail
    )

    assert product_of(db_session, resolution).model_code == "MK-LA001"


def test_existing_offer_of_another_category_does_not_get_foreign_specs(
    db_session: Session,
) -> None:
    mouse = item("Chuột không dây Pulsar X2", slug="x")
    res = resolve_product(db_session, Category.mouse, mouse, None)
    store(db_session, res, mouse)
    before = dict(product_of(db_session, res).specs)

    again = resolve_product(
        db_session,
        Category.keyboard,
        item("Bàn phím cơ Pulsar X2 Tactile switch", slug="x"),
        None,
    )

    assert again.product_id == res.product_id
    assert product_of(db_session, res).specs == before
    assert product_of(db_session, res).category is Category.mouse


def test_find_existing_offer_sees_the_other_scheme(db_session: Session) -> None:
    first = item("Chuột Pulsar X2 Red", slug="red")
    store(db_session, resolve_product(db_session, Category.mouse, first, None), first)
    offers = OfferRepository(db_session)

    stored = offers.get_by_url(str(first.url))
    assert stored is not None
    http_form = str(first.url).replace("https://", "http://")
    assert find_existing_offer(offers, http_form) == stored
    assert find_existing_offer(offers, "https://gearvn.example/p/none") is None


# ---- repository ----
def test_list_by_brand_filters_by_category_and_brand_in_id_order(db_session: Session) -> None:
    repo = ProductRepository(db_session)
    a = repo.add(Product(category=Category.mouse, brand="Pulsar", canonical_name="a"))
    b = repo.add(Product(category=Category.mouse, brand="Pulsar", canonical_name="b"))
    repo.add(Product(category=Category.mouse, brand="Razer", canonical_name="c"))
    repo.add(Product(category=Category.keyboard, brand="Pulsar", canonical_name="d"))

    assert [p.id for p in repo.list_by_brand(Category.mouse, "Pulsar")] == [a.id, b.id]
    assert repo.list_by_brand(Category.headset, "Pulsar") == []


def test_set_model_code_enforces_the_unique_key(db_session: Session) -> None:
    repo = ProductRepository(db_session)
    first = repo.add(Product(category=Category.mouse, brand="Pulsar", canonical_name="a"))
    second = repo.add(Product(category=Category.mouse, brand="Pulsar", canonical_name="b"))
    repo.set_model_code(first, "PX2")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        repo.set_model_code(second, "PX2")
