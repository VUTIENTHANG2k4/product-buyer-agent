"""detect_brand (app/normalize/brand.py)."""

import unicodedata

import pytest

from app.normalize.brand import UNKNOWN_BRAND, detect_brand


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("ASUS ROG Strix G16 G614JV", "ASUS"),
        ("Laptop Acer Nitro 5 AN515-57", "Acer"),
        ("Laptop gaming MSI Katana 15", "MSI"),
        ("Chuột Logitech G304 không dây", "Logitech"),
        ("Chuột không dây Razer DeathAdder", "Razer"),
        ("Bàn phím cơ Akko 3068B", "Akko"),
        ("Tai nghe HyperX Cloud II", "HyperX"),
        ("tai nghe corsair hs80", "Corsair"),
        ("Dare-U EK87", "DareU"),
        ("E-Dra EK375", "E-Dra"),
        ("ThinkPad X1 Carbon Gen 11", "Lenovo"),
        ("Legion 5 Pro 16ACH6H", "Lenovo"),
        ("MacBook Air M2 13 inch", "Apple"),
        ("HP Victus 15-fa1139TX", "HP"),
        ("Hewlett Packard ProBook 450", "HP"),
        ("Logi MX Master 3S", "Logitech"),
        ("SteelSeries Arctis Nova 7", "SteelSeries"),
    ],
)
def test_detects_known_brands_at_the_start_of_the_title(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cho MacBook Pro",  # Apple chỉ xuất hiện sau
        "Balo laptop chống sốc",
        "Hpsomething 15",  # không phải từ "hp"
        "Asusxyz",
        "",
        "   ",
    ],
)
def test_unknown_when_brand_is_not_at_the_start(title: str) -> None:
    assert detect_brand(title) == UNKNOWN_BRAND


def test_ignores_accents_case_and_unicode_form() -> None:
    nfd = unicodedata.normalize("NFD", "Chuột Logitech G102")
    assert detect_brand(nfd) == "Logitech"
    assert detect_brand("CHUOT LOGITECH G102") == "Logitech"
