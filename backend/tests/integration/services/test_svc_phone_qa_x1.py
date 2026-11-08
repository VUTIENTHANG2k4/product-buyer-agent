"""QA X1: điện thoại qua `CatalogService`/`CompareService` và bộ lọc thông số (PostgreSQL thật)."""

import pytest
from sqlmodel import Session

from app.domain.catalog import CatalogFilters
from app.domain.dto import SpecFilter
from app.domain.enums import Category, SiteKey
from app.domain.errors import ValidationFailed
from app.services.catalog_service import CatalogService
from app.services.compare_service import CompareService
from app.services.spec_filters import parse_spec_filters, spec_fields
from app.services.views import MAX_KEY_SPECS
from tests.service_support import add_offer, add_product, clock

PHONE = Category.phone


def phone(session: Session, name: str, specs: dict[str, object], price: int = 10_000_000) -> int:
    product = add_product(
        session,
        category=PHONE,
        brand="Mock",
        model_code=None,
        canonical_name=name,
        specs=specs,
    )
    add_offer(session, product, site=SiteKey.nguyenkim, price=price)
    assert product.id is not None
    return product.id


def search(session: Session, *specs: SpecFilter, **kwargs: object) -> list[int]:
    filters = CatalogFilters.model_validate(
        {"category": PHONE, "spec_filters": list(specs), "limit": 100, **kwargs}
    )
    return [item.product_id for item in CatalogService(session, now=clock).search(filters).items]


def test_phone_filter_fields_are_exactly_the_phone_specs() -> None:
    fields = {info.name: info for info in spec_fields(PHONE)}
    assert set(fields) == {"chipset", "ram_gb", "storage_gb", "screen_in", "battery_mah", "os"}
    assert fields["ram_gb"].kind == "integer"
    assert fields["screen_in"].kind == "number"
    assert fields["chipset"].kind == "string"


def test_a_laptop_only_field_is_rejected_for_phones() -> None:
    with pytest.raises(ValidationFailed):
        parse_spec_filters({"spec.gpu_rank__gte": "40"}, PHONE)
    with pytest.raises(ValidationFailed):
        parse_spec_filters({"spec.ram_gb__contains": "8"}, PHONE)
    with pytest.raises(ValidationFailed):
        parse_spec_filters({"spec.ram_gb__gte": "tám"}, PHONE)


def test_ram_filter_excludes_phones_whose_ram_is_unknown(db_session: Session) -> None:
    eight = phone(db_session, "A", {"ram_gb": 8, "storage_gb": 128})
    twelve = phone(db_session, "B", {"ram_gb": 12, "storage_gb": 256})
    unknown = phone(db_session, "iPhone", {"storage_gb": 128})  # iPhone không ghi RAM

    assert set(search(db_session, SpecFilter(field="ram_gb", op="gte", value=8))) == {eight, twelve}
    assert search(db_session, SpecFilter(field="ram_gb", op="gte", value=12)) == [twelve]
    assert unknown in search(db_session)  # không lọc thì vẫn thấy máy chưa rõ RAM


def test_storage_terabyte_phone_is_found_by_gigabyte_value(db_session: Session) -> None:
    tb = phone(db_session, "1TB", {"storage_gb": 1000})
    gb = phone(db_session, "128", {"storage_gb": 128})

    assert search(db_session, SpecFilter(field="storage_gb", op="eq", value=1000)) == [tb]
    assert search(db_session, SpecFilter(field="storage_gb", op="lte", value=128)) == [gb]
    assert search(db_session, SpecFilter(field="storage_gb", op="gte", value=2000)) == []


def test_chipset_and_os_text_filters_ignore_case_and_wildcards(db_session: Session) -> None:
    snap = phone(db_session, "S", {"chipset": "Snapdragon 8 Elite", "os": "Android 15"})
    apple = phone(db_session, "A", {"chipset": "Apple A18", "os": "iOS 18"})

    assert search(db_session, SpecFilter(field="chipset", op="contains", value="SNAPDRAGON")) == [
        snap
    ]
    assert search(db_session, SpecFilter(field="os", op="contains", value="ios")) == [apple]
    assert search(db_session, SpecFilter(field="chipset", op="contains", value="%")) == []
    assert search(db_session, SpecFilter(field="chipset", op="contains", value="_")) == []


def test_screen_and_battery_boundaries_are_inclusive(db_session: Session) -> None:
    small = phone(db_session, "small", {"screen_in": 6.1, "battery_mah": 3500})
    big = phone(db_session, "big", {"screen_in": 6.7, "battery_mah": 5000})

    assert search(db_session, SpecFilter(field="screen_in", op="lte", value=6.1)) == [small]
    assert search(db_session, SpecFilter(field="screen_in", op="gte", value=6.7)) == [big]
    assert search(db_session, SpecFilter(field="battery_mah", op="gte", value=5000)) == [big]
    assert search(db_session, SpecFilter(field="battery_mah", op="gte", value=5001)) == []


def test_search_summary_shows_the_phone_key_specs_in_the_phone_order(db_session: Session) -> None:
    phone(
        db_session,
        "Full",
        {
            "os": "Android",
            "battery_mah": 5000,
            "screen_in": 6.7,
            "chipset": "Dimensity",
            "storage_gb": 256,
            "ram_gb": 8,
            "extra_field": "bị loại",
        },
    )
    filters = CatalogFilters(category=PHONE)
    (item,) = CatalogService(db_session, now=clock).search(filters).items
    assert list(item.key_specs) == [
        "ram_gb",
        "storage_gb",
        "chipset",
        "screen_in",
        "battery_mah",
        "os",
    ]
    assert len(item.key_specs) <= MAX_KEY_SPECS


def test_phone_without_any_specs_still_appears_with_empty_key_specs(db_session: Session) -> None:
    phone(db_session, "Nokia 105", {})
    (item,) = CatalogService(db_session, now=clock).search(CatalogFilters(category=PHONE)).items
    assert item.key_specs == {}


def test_phones_do_not_leak_into_other_categories(db_session: Session) -> None:
    phone(db_session, "P", {"ram_gb": 8})
    laptop = add_product(db_session, category=Category.laptop)
    add_offer(db_session, laptop)
    assert len(search(db_session)) == 1
    only_laptops = CatalogFilters(category=Category.laptop)
    assert len(CatalogService(db_session, now=clock).search(only_laptops).items) == 1


def test_compare_of_phones_marks_missing_ram_as_a_difference(db_session: Session) -> None:
    a = phone(db_session, "iPhone", {"storage_gb": 128}, 20_000_000)
    b = phone(db_session, "Galaxy", {"ram_gb": 8, "storage_gb": 128}, 15_000_000)
    result = CompareService(db_session, now=clock).compare([a, b])
    assert result.differing_fields == ["ram_gb"]
    assert result.cheapest_product_id == b


def test_compare_of_a_phone_and_a_laptop_still_works_on_the_union_of_fields(
    db_session: Session,
) -> None:
    a = phone(db_session, "Phone", {"ram_gb": 8, "battery_mah": 5000})
    laptop = add_product(db_session, specs={"ram_gb": 16, "gpu_rank": 40})
    add_offer(db_session, laptop)
    assert laptop.id is not None
    result = CompareService(db_session, now=clock).compare([a, laptop.id])
    assert result.differing_fields == ["ram_gb", "battery_mah", "gpu_rank"]
