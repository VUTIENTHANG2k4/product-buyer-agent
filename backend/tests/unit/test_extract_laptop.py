"""Bộ trích xuất thông số laptop theo luật (app/normalize/specs/laptop.py)."""

from typing import Any

import pytest

from app.normalize.specs.laptop import extract_laptop


def dump(title: str, raw_specs: dict[str, str] | None = None) -> dict[str, Any]:
    return extract_laptop(title, raw_specs or {}).model_dump(mode="json", exclude_none=True)


@pytest.mark.parametrize(
    ("title", "cpu_model", "vendor"),
    [
        ("Laptop X (Intel Core i5-13420H | 16GB)", "i5-13420H", "intel"),
        ("Laptop X i5-14450HX/16GB/512GB", "i5-14450HX", "intel"),
        ("Laptop X (Core Ultra 9 386H | RTX 5060)", "Core Ultra 9 386H", "intel"),
        ("Laptop X (Intel Core Ultra5-115U)", "Core Ultra 5 115U", "intel"),
        ("Laptop X (Ultra 5-226V/ 16GB)", "Core Ultra 5 226V", "intel"),
        ("Laptop X (Intel Core Ultra 5 Processor 225H)", "Core Ultra 5 225H", "intel"),
        ("Laptop X (Core 5-120U/ 8GB)", "Core 5 120U", "intel"),
        ("Laptop X (Intel Core 7 350 | 16GB)", "Core 7 350", "intel"),
        ("Laptop X (Ryzen 7-7735HS/ RTX 3050)", "Ryzen 7 7735HS", "amd"),
        ("Laptop X (AMD Ryzen 3 - 3200U | AMD Radeon Vega 3)", "Ryzen 3 3200U", "amd"),
        ("Laptop X (AMD Ryzen™ 7 8845HS | RTX 3050)", "Ryzen 7 8845HS", "amd"),
        ("Laptop X (Ryzen AI 9 HX 370 | 32GB)", "Ryzen AI 9 HX 370", "amd"),
        ("Laptop X R7 7730U/8GB/512GB", "Ryzen 7 7730U", "amd"),
        (
            "Laptop X (Snapdragon X Plus X1P-64-100 | 16GB)",
            "Snapdragon X Plus X1P-64-100",
            "qualcomm",
        ),
        ("Laptop X (Intel Celeron N4500 | 8GB)", "Celeron N4500", "intel"),
        ("MacBook Air M3 13 inch 16GB 512GB", "Apple M3", "apple"),
    ],
)
def test_cpu_model_and_vendor_are_normalized(title: str, cpu_model: str, vendor: str) -> None:
    specs = dump(title)
    assert specs["cpu_model"] == cpu_model
    assert specs["cpu_vendor"] == vendor


def test_cpu_is_absent_when_the_title_has_no_cpu() -> None:
    assert "cpu_model" not in dump("Laptop Acer Aspire Lite 15 AL15-53P-56QH")


def test_cpu_falls_back_to_the_family_label_when_title_has_no_model() -> None:
    specs = dump("Laptop Acer Aspire Lite 15", {"Dòng CPU": "Core 5"})
    assert specs["cpu_model"] == "Core 5"
    assert specs["cpu_vendor"] == "intel"


def test_title_cpu_wins_over_the_less_specific_label() -> None:
    specs = dump("Laptop X (Core 5-120U/ 8GB)", {"Dòng CPU": "Core 5"})
    assert specs["cpu_model"] == "Core 5 120U"


@pytest.mark.parametrize(
    ("title", "gpu", "vram", "rank"),
    [
        ("Laptop X (Core 5-210H/ RTX 3050 4GB/ 16GB/ 512GB)", "RTX 3050", 4, 20),
        ("Laptop X (i7 | RTX 4050 6GB GDDR6 | 15.6 inch | 16GB | 512GB)", "RTX 4050", 6, 30),
        ('Laptop X i5-14450HX/16GB/512GB/16"/Nvidia Geforce RTX5050 8GB/Win 11', "RTX 5050", 8, 34),
        ("Laptop X (Core 5-210H/ RTX 3050/ 16GB/ 512GB)", "RTX 3050", None, 20),
        ("Laptop X (Core Ultra 9 | RTX 5060 | 16 inch | 32GB | 1TB)", "RTX 5060", None, 45),
        ("Laptop X (Core 7 | RTX 5090 | 64GB | 2TB)", "RTX 5090", None, 85),
    ],
)
def test_discrete_gpu_vram_is_read_only_when_adjacent(
    title: str, gpu: str, vram: int | None, rank: int
) -> None:
    specs = dump(title)
    assert specs["gpu_model"] == gpu
    assert specs.get("gpu_vram_gb") == vram
    assert specs["gpu_rank"] == rank
    assert specs["is_gaming"] is True


@pytest.mark.parametrize(
    "title",
    [
        "Laptop X (Intel Core 5 120U | 16GB | 512GB | Intel Graphics | 15.6 inch FHD)",
        "Laptop X (Ryzen 5 40 | 16GB | 512GB | AMD Radeon | 15.6 inch FHD)",
        "Laptop X (Core Ultra 7 | Intel Arc Graphics | 14 inch)",
        "Laptop X (Core Ultra 7 155H | 16GB | 512GB | Intel Arc | 15.6 inch)",
        "Laptop X (Snapdragon X Plus | 16GB | 512GB | Qualcom Adreno | 14 inch)",
    ],
)
def test_integrated_gpu_is_recognised_and_not_gaming(title: str) -> None:
    specs = dump(title)
    assert specs["gpu_model"] == "Integrated"
    assert specs["gpu_rank"] == 0
    assert specs["is_gaming"] is False
    assert "gpu_vram_gb" not in specs


def test_gaming_word_makes_a_laptop_gaming_even_without_gpu_info() -> None:
    specs = dump("Laptop gaming ASUS V16 V3607VJ (Core 5-210H/ 16GB/ 512GB)")
    assert specs["is_gaming"] is True
    assert "gpu_model" not in specs


def test_is_gaming_is_unknown_without_any_evidence() -> None:
    assert "is_gaming" not in dump("Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB)")


def test_gpu_label_wins_over_title() -> None:
    specs = dump(
        "Laptop Acer X", {"Card đồ hoạ": "NVIDIA GeForce RTX 5050 8GB GDDR7", "CPU": "Core i5"}
    )
    assert (specs["gpu_model"], specs["gpu_vram_gb"]) == ("RTX 5050", 8)


@pytest.mark.parametrize(
    ("title", "ram", "storage"),
    [
        ('Laptop X (Core 5/ 12GB/ 512GB/ 14" FHD+)', 12, 512),
        ("Laptop X (Intel Core i5 | RTX 3050 6GB | 16GB | 512GB)", 16, 512),
        ("Laptop X (Intel Core i7 | 8 GB | 512 GB | Windows 11)", 8, 512),
        ("Laptop X (Intel Core Ultra 9 | 64GB | 2TB)", 64, 2000),
        ('Laptop X (Core 7-7735HS/ RTX 3050 6GB/ 16GB/ 1TB/ 15.6")', 16, 1000),
        ("Laptop X 512GB/16GB", 16, 512),  # thứ tự ngược vẫn đúng nhờ giá trị
        ("Laptop X (Core 5 | 256GB)", None, 256),
        ("Laptop X (Core 5 | 16GB)", 16, None),
        ("Laptop X (Core 5)", None, None),
    ],
)
def test_ram_and_storage_are_told_apart_by_size_and_order(
    title: str, ram: int | None, storage: int | None
) -> None:
    specs = dump(title)
    assert specs.get("ram_gb") == ram
    assert specs.get("storage_gb") == storage


def test_vram_is_not_mistaken_for_ram() -> None:
    specs = dump("Laptop X (Core 5 | RTX 4050 6GB | 16GB | 512GB)")
    assert (specs["ram_gb"], specs["storage_gb"]) == (16, 512)


def test_detail_labels_win_for_ram_and_storage() -> None:
    specs = dump(
        "Laptop HP Victus",
        {
            "RAM": "16GB DDR4-3200 MHz (1x16GB còn 1 khe)",
            "Ổ cứng": "512 GB PCIe® Gen4 NVMe™ TLC M.2 SSD",
            "Ổ cứng / Ổ đĩa quang (ODD)": "Không",
        },
    )
    assert (specs["ram_gb"], specs["storage_gb"], specs["storage_type"]) == (16, 512, "ssd")


@pytest.mark.parametrize(
    ("title", "inches", "resolution", "hertz", "panel"),
    [
        ('Laptop X (14" FHD+ IPS 120Hz)', 14.0, "1920x1200", 120, "IPS"),
        ("Laptop X (15.6 inch FHD 144Hz)", 15.6, "1920x1080", 144, None),
        ('Laptop X (16" WUXGA 144Hz)', 16.0, "1920x1200", 144, None),
        ("Laptop X (16 inch 2.5K OLED 240Hz)", 16.0, None, 240, "OLED"),  # 2.5K mơ hồ
        ("Laptop X (13.4 inch QHD 2.5K 120Hz)", 13.4, None, 120, None),  # QHD mơ hồ
        ("Laptop X (15.6-inch FHD)", 15.6, "1920x1080", None, None),
        ("Laptop X 15.6 inch 1920 x 1080", 15.6, "1920x1080", None, None),
        ("Laptop X (14 inch 4K OLED)", 14.0, "3840x2160", None, "OLED"),
    ],
)
def test_screen_fields(
    title: str, inches: float, resolution: str | None, hertz: int | None, panel: str | None
) -> None:
    specs = dump(title)
    assert specs["screen_in"] == inches
    assert specs.get("resolution") == resolution
    assert specs.get("refresh_hz") == hertz
    assert specs.get("panel") == panel


def test_implausible_screen_size_is_dropped() -> None:
    assert "screen_in" not in dump('Laptop X 75" 4K')


@pytest.mark.parametrize(
    ("title", "os_name"),
    [
        ("Laptop X (… / Win 11)", "Windows 11"),
        ("Laptop X (… | Windows 11 Home 64 | Bạc)", "Windows 11 Home"),
        ("Laptop X (… | Windows 11 Pro | Xám)", "Windows 11 Pro"),
        ("Laptop X/Win11", "Windows 11"),
        ("Laptop X (… / FreeDOS)", "FreeDOS"),
        ("Laptop X (… / No OS)", "FreeDOS"),
    ],
)
def test_operating_system(title: str, os_name: str) -> None:
    assert dump(title)["os"] == os_name


def test_full_detail_table_of_an_anphat_laptop() -> None:
    specs = dump(
        "Laptop HP VICTUS 15-fa2452TX D44VLPA",
        {
            "CPU": "Intel Core i5-13420H (up to 4.6 GHz with Intel® Turbo Boost Technology)",
            "VGA": "NVIDIA® GeForce RTX 3050 Laptop GPU (6 GB GDDR6 dedicated)",
            "Màn hình": "15.6 inch FHD (1920 x 1080), 144 Hz, IPS, micro-edge",
            "RAM": "16GB DDR4-3200 MHz (1x16GB còn 1 khe)",
            "Ổ cứng": "512 GB PCIe® Gen4 NVMe™ TLC M.2 SSD",
            "Cân nặng": "2.29 kg",
            "OS": "Windows 11 Home",
            "Nhóm thuộc tính": "Laptop | Laptop Gaming | HP Victus",
        },
    )
    assert specs == {
        "cpu_model": "i5-13420H",
        "cpu_vendor": "intel",
        "gpu_model": "RTX 3050",
        "gpu_vram_gb": 6,
        "gpu_rank": 20,
        "ram_gb": 16,
        "storage_gb": 512,
        "storage_type": "ssd",
        "screen_in": 15.6,
        "resolution": "1920x1080",
        "refresh_hz": 144,
        "panel": "IPS",
        "weight_kg": 2.29,
        "os": "Windows 11 Home",
        "is_gaming": True,
    }


@pytest.mark.parametrize(
    "title",
    ["", "   ", "\x00\x00", 'Laptop \x00 weird 99999GB 0" 0Hz', "RTX " * 500, "Ryzen 7 " * 300],
)
def test_hostile_or_empty_input_never_raises(title: str) -> None:
    extract_laptop(title, {"RAM": "-5 GB", "CPU": "\x00", "Màn hình": "x" * 10_000})


def test_empty_input_gives_empty_specs() -> None:
    assert dump("") == {}


def test_onboard_ram_in_the_title_is_not_an_integrated_gpu() -> None:
    specs = dump("Laptop Lenovo IdeaPad Slim 3 i5-13420H 16GB onboard 512GB")
    assert "gpu_model" not in specs and specs["ram_gb"] == 16


def test_onboard_next_to_a_discrete_gpu_keeps_the_discrete_gpu() -> None:
    specs = dump("Laptop MSI Thin 15 i5-13420H 16GB onboard 512GB RTX 3050")
    assert specs["gpu_model"] == "RTX 3050"


def test_onboard_graphics_is_still_an_integrated_gpu() -> None:
    assert dump("Laptop Foo Bar i5-13420H 8GB 256GB onboard graphics")["gpu_model"] == "Integrated"


def test_capacity_does_not_read_the_tail_of_a_number_with_a_thousands_separator() -> None:
    assert "storage_gb" not in dump("Laptop Foo Bar i5-13420H 8GB", {"Ổ cứng": "Up to 1,000GB"})


def test_upgrade_limit_labels_are_not_read_as_the_installed_ram_or_storage() -> None:
    specs = dump(
        "Laptop Foo Bar i5-13420H",
        {
            "Nâng cấp RAM": "Tối đa 64GB",
            "RAM": "16GB",
            "Khả năng nâng cấp ổ cứng": "Tối đa 2TB",
            "Ổ cứng": "512GB SSD",
        },
    )
    assert (specs["ram_gb"], specs["storage_gb"]) == (16, 512)
