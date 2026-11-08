"""Điện thoại (X1.2): trích xuất thông số, hãng, tên chuẩn và khóa so sánh (docs/04 §5.5, §7)."""

import pytest

from app.domain.enums import Category
from app.normalize.brand import UNKNOWN_BRAND, detect_brand
from app.normalize.extract import extract_specs
from app.normalize.names import canonical_name, name_key
from app.normalize.specs import REQUIRED_FIELDS, SPEC_MODELS
from app.normalize.specs.phone import PhoneSpecs, extract_phone


def _specs(title: str, raw: dict[str, str] | None = None) -> dict[str, object]:
    return extract_phone(title, raw or {}).model_dump(exclude_none=True)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Samsung Galaxy A57 5G 8GB 128GB", {"ram_gb": 8, "storage_gb": 128}),
        ("Điện thoại Samsung Galaxy A08 4G (4GB, 64GB ) Green", {"ram_gb": 4, "storage_gb": 64}),
        ("Điện thoại Honor Magic V5 16GB/512GB Vàng", {"ram_gb": 16, "storage_gb": 512}),
        ("ĐTDĐ Samsung S26 SM-S942B/DS, 12GB+256GB, Xanh", {"ram_gb": 12, "storage_gb": 256}),
        ("Điện thoại Samsung Galaxy A07 LTE (4Gb/128Gb)", {"ram_gb": 4, "storage_gb": 128}),
        ("iPhone 16 128GB", {"storage_gb": 128}),
        ("iPhone 18 Pro Max 1TB Đen", {"storage_gb": 1000}),
        ("iPhone 18 Pro 2TB Bạc", {"storage_gb": 2000}),
    ],
)
def test_memory_is_read_from_the_title(title: str, expected: dict[str, int]) -> None:
    assert _specs(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Nothing Phone 4a 12GB",  # một dung lượng dưới 32 GB: RAM hay bộ nhớ trong?
        "Điện thoại Redmi 12 8GB(+8GB)/256GB",  # ba dung lượng (RAM mở rộng)
        "Điện thoại Mock 128GB/8GB",  # thứ tự ngược
        "Điện thoại Nokia HMD 105 4G Pro",  # "4G" là mạng, không phải dung lượng
    ],
)
def test_ambiguous_memory_in_the_title_is_left_empty(title: str) -> None:
    assert _specs(title) == {}


def test_table_labels_fill_what_the_title_does_not_say() -> None:
    raw = {"Dung lượng RAM": "8 GB", "Bộ nhớ trong": "128 GB"}
    assert _specs("iPhone 16 128GB", raw) == {"ram_gb": 8, "storage_gb": 128}
    assert _specs("iPhone 16", raw) == {"ram_gb": 8, "storage_gb": 128}


def test_title_wins_over_a_conflicting_label() -> None:
    assert _specs("Điện thoại X 8GB/256GB", {"RAM": "12 GB", "Bộ nhớ trong": "512 GB"}) == {
        "ram_gb": 8,
        "storage_gb": 256,
    }


def test_a_label_listing_several_options_or_a_limit_is_not_a_value() -> None:
    raw = {"Bộ nhớ trong": "128GB, 256GB, 512GB", "Hỗ trợ thẻ nhớ tối đa": "1TB"}
    assert _specs("iPhone 16", raw) == {}


@pytest.mark.parametrize(
    ("label", "value", "expected"),
    [
        ("Dung lượng pin", "5.000 mAh, 45 W", 5000),
        ("Pin", "5,000mAh", 5000),
        ("Dung lượng pin", "6000 mAh", 6000),
        ("Công nghệ sạc pin", "Sạc nhanh 45W", None),
        ("Dung lượng pin", "50 mAh", None),  # ngoài miền hợp lý
    ],
)
def test_battery_is_read_from_labels(label: str, value: str, expected: int | None) -> None:
    assert _specs("Điện thoại Mock X", {label: value}).get("battery_mah") == expected


def test_battery_can_come_from_the_title() -> None:
    assert _specs("Điện thoại Samsung Galaxy A08 Pin 6000mAh").get("battery_mah") == 6000


@pytest.mark.parametrize(
    ("title", "raw", "expected"),
    [
        ("Samsung Galaxy A57", {"Kích thước màn hình": "6.7 inch"}, 6.7),
        ("Samsung Galaxy A57", {"Kích thước màn hình": "6,1"}, 6.1),  # nhãn chỉ ghi số
        ("ĐTDĐ Galaxy A37 5G (Exynos 1480/8GB/128GB/ 6.7” FHD+,120Hz/Violet)", {}, 6.7),
        ("Samsung Galaxy A57", {"Màn hình": "Super AMOLED 6.7 inch"}, 6.7),
        ("Samsung Galaxy A57", {"Kích thước màn hình": "60"}, None),  # ngoài miền hợp lý
        ("Samsung Galaxy A57", {}, None),
    ],
)
def test_screen_size(title: str, raw: dict[str, str], expected: float | None) -> None:
    assert _specs(title, raw).get("screen_in") == expected


def test_chipset_and_os_come_only_from_the_table() -> None:
    raw = {"Chip xử lý (CPU)": "Apple A18", "Hệ điều hành": "iOS 18"}
    assert _specs("iPhone 16 128GB", raw)["chipset"] == "Apple A18"
    assert _specs("iPhone 16 128GB", raw)["os"] == "iOS 18"
    assert "chipset" not in _specs("iPhone 16 128GB")
    assert "os" not in _specs("iPhone 16 128GB")


def test_extract_specs_reports_ram_as_missing_for_an_iphone_title() -> None:
    result = extract_specs(Category.phone, "Điện thoại iPhone 18 Pro Max 256GB Đen")
    assert result.specs == {"storage_gb": 256}
    assert result.missing == ("ram_gb",)
    assert result.confidence == 0.24


def test_extract_specs_is_complete_with_ram_and_storage() -> None:
    result = extract_specs(Category.phone, "Điện thoại OPPO Reno16F 8GB/256GB Trắng (CPH2859)")
    assert (result.missing, result.confidence) == ((), 1.0)


def test_phone_is_registered_with_ram_and_storage_as_required_fields() -> None:
    assert SPEC_MODELS[Category.phone] is PhoneSpecs
    assert REQUIRED_FIELDS[Category.phone] == ("ram_gb", "storage_gb")


def test_garbage_input_does_not_raise() -> None:
    assert _specs("x" * 100_000, {"RAM": "9" * 5000}) == {}


# ---- hãng ----
@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Điện thoại Samsung Galaxy A57 5G", "Samsung"),
        ("ĐTDĐ Galaxy A37 5G (Exynos 1480/8GB/128GB)", "Samsung"),
        ("Điện thoại iPhone 16 128GB", "Apple"),
        ("Điện thoại Xiaomi Redmi Note 13 Pro", "Xiaomi"),
        ("Điện thoại OPPO Reno16F 8GB/256GB", "OPPO"),
        ("Điện thoại vivo Y19s", "vivo"),
        ("Điện thoại Nokia HMD 105 4G", "Nokia"),
        ("Máy tính bảng Honor Pad X8b 6GB/128GB", "Honor"),
        ("Điện thoại Google Pixel 9", "Google"),
        ("Benco S1 Pro 8GB 256GB", "Benco"),  # gặp khi chạy thật FPT Shop (X1.7)
        ("Laptop ASUS Vivobook 14", "ASUS"),  # "vivo" chỉ khớp khi đứng riêng
    ],
)
def test_phone_brands_are_detected_after_the_product_type(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


@pytest.mark.parametrize("title", ["Ốp lưng iPhone 16", "Cáp sạc iPhone", "Kính cường lực Samsung"])
def test_accessories_for_a_phone_are_not_assigned_to_its_brand(title: str) -> None:
    assert detect_brand(title) == UNKNOWN_BRAND


# ---- tên chuẩn và khóa so sánh ----
@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Điện thoại iPhone 18 Pro Max 256GB Đỏ Burgundy", "iPhone 18 Pro Max 256GB"),
        ("Điện thoại iPhone 17 Pro 256GB Cam Vũ Trụ (MG8H4ZP/A)", "iPhone 17 Pro 256GB"),
        (
            "Điện thoại Samsung Galaxy A18 (6GB/128GB) bạc SM-A185GZSLXXV",
            "Samsung Galaxy A18 6GB 128GB",
        ),
        (
            "ĐTDĐ Samsung S26 SM-S942B/DS, 12GB+256GB, Xanh dương, SM-S942BLBCXXV",
            "Samsung S26 SM-S942B DS 12GB 256GB",
        ),
        (
            "Điện thoại Samsung Galaxy A07 LTE (4Gb/128Gb), Black ",
            "Samsung Galaxy A07 LTE 4Gb 128Gb",
        ),
        (
            "Điện thoại Samsung Galaxy A57 5G 8GB/128GB 5G xanh",
            "Samsung Galaxy A57 5G 8GB 128GB 5G",
        ),
        ("Điện thoại Nokia 105 4G Pro Xanh", "Nokia 105 4G Pro"),
    ],
)
def test_canonical_phone_name_keeps_memory_and_drops_colour_and_part_codes(
    title: str, name: str
) -> None:
    assert canonical_name(title, Category.phone) == name


def test_phone_without_memory_in_the_title_keeps_its_trailing_words() -> None:
    title = "Điện thoại Nokia HMD 105 4G TA-1651 DS VN Đen"
    assert canonical_name(title, Category.phone) == "Nokia HMD 105 4G TA-1651 DS VN"


def test_name_key_differs_by_storage_and_ignores_colour() -> None:
    def key(title: str) -> tuple[str, ...]:
        return name_key(canonical_name(title, Category.phone), detect_brand(title))

    assert key("Điện thoại iPhone 17 256GB Đen (MG6J4ZP/A)") == key(
        "Điện thoại iPhone 17 256GB Trắng (MG6K4ZP/A)"
    )
    assert key("Điện thoại iPhone 17 256GB Đen") != key("Điện thoại iPhone 17 512GB Đen")
