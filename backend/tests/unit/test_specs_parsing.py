"""Hàm đọc giá trị thông số (app/normalize/specs/parsing.py)."""

import pytest
from pydantic import BaseModel

from app.normalize.specs.parsing import (
    build_specs,
    capacities_gb,
    clean,
    first_capacity_gb,
    has_word,
    label_values,
    parse_grams,
    parse_hertz,
    parse_inches,
    parse_kilograms,
    peripheral_connection,
    read_connectivity,
)
from app.normalize.specs.types import PeripheralConnection, PositiveInt
from app.normalize.text import fold


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("512GB", [512]),
        ("512 GB PCIe Gen4 NVMe", [512]),
        ("1TB", [1000]),
        ("1 TB SSD", [1000]),
        ("16GB/ 512GB / 2TB", [16, 512, 2000]),
        ("16GB DDR4-3200 MHz (1x16GB còn 1 khe)", [16]),
        ("up to 4.6 GHz, 12 MB L3 cache", []),
        ("Wi-Fi 6, Bluetooth 5.4", []),
        ("", []),
    ],
)
def test_capacities_are_read_in_gigabytes(text: str, expected: list[int]) -> None:
    assert capacities_gb(text) == expected


def test_first_capacity_is_none_without_a_unit() -> None:
    assert first_capacity_gb("Full HD") is None
    assert first_capacity_gb("8 GB") == 8


@pytest.mark.parametrize(
    ("text", "inches"),
    [
        ('15.6"', 15.6),
        ("15.6 inch FHD", 15.6),
        ("15.6-inch FHD", 15.6),
        ('14.0" FHD+', 14.0),
        ("16 inch", 16.0),
        ("13,4 inch QHD", 13.4),
    ],
)
def test_screen_size_in_inches(text: str, inches: float) -> None:
    assert parse_inches(text) == inches


@pytest.mark.parametrize("text", ["FHD 144Hz", "Màn hình lớn", "1920 x 1080", ""])
def test_screen_size_is_none_without_inch_marker(text: str) -> None:
    assert parse_inches(text) is None


@pytest.mark.parametrize(
    ("text", "hertz"), [("FHD 144Hz", 144), ("IPS 120 Hz", 120), ("240hz OLED", 240)]
)
def test_refresh_rate(text: str, hertz: int | None) -> None:
    assert parse_hertz(text) == hertz


def test_refresh_rate_ignores_other_units() -> None:
    assert parse_hertz("up to 4.6 GHz") is None


@pytest.mark.parametrize(
    ("text", "grams"),
    [("59 g", 59), ("975g", 975), ("Khoảng 975g (không có cáp)", 975), ("0.06 kg", 60)],
)
def test_weight_in_grams(text: str, grams: int) -> None:
    assert parse_grams(text) == grams


@pytest.mark.parametrize(
    ("text", "kilograms"), [("2.29 kg", 2.29), ("2,2 kg", 2.2), ("975 g", 0.975), ("1.8kg", 1.8)]
)
def test_weight_in_kilograms(text: str, kilograms: float) -> None:
    assert parse_kilograms(text) == kilograms


@pytest.mark.parametrize("text", ["", "nhẹ", "0 g", "0 kg"])
def test_weight_is_none_when_unreadable_or_zero(text: str) -> None:
    assert parse_grams(text) is None
    assert parse_kilograms(text) is None


def test_label_values_match_folded_aliases_in_priority_order() -> None:
    raw = {
        "Bộ nhớ trong (RAM) / Số khe cắm": "2 khe",
        "Bộ nhớ trong (RAM) / Dung lượng": "16 GB",
        "RAM": "",
        "Ổ cứng": "512 GB",
    }
    values = list(label_values(raw, ("bo nho trong (ram) / dung luong", "ram")))
    assert values == ["16 GB", "2 khe"]  # nhãn cụ thể trước, giá trị rỗng bị bỏ
    assert list(label_values(raw, ("o cung",))) == ["512 GB"]


def test_label_values_of_missing_label_is_empty() -> None:
    assert list(label_values({"Màu": "Đen"}, ("cpu",))) == []


def test_clean_collapses_whitespace_and_truncates() -> None:
    assert clean("  a \n  b\t c ") == "a b c"
    assert len(clean("x" * 10_000)) == 2000


def test_has_word_requires_whole_word() -> None:
    assert has_word("laptop gaming a16", "gaming")
    assert not has_word("gamingx", "gaming")
    assert not has_word("xgaming", "gaming")


class _Probe(BaseModel):
    count: PositiveInt | None = None
    name: str | None = None


def test_build_specs_drops_only_the_invalid_field() -> None:
    probe = build_specs(_Probe, {"count": -5, "name": "ok"})
    assert probe.model_dump() == {"count": None, "name": "ok"}


def test_build_specs_skips_none_values_and_ignores_unknown_fields() -> None:
    assert build_specs(_Probe, {"count": None, "extra": 1}).model_dump() == {
        "count": None,
        "name": None,
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("chuột không dây logitech", [PeripheralConnection.wireless_2_4]),
        ("chuột có dây logitech", [PeripheralConnection.wired]),
        ("chuột bluetooth silent", [PeripheralConnection.bluetooth]),
        (
            "bàn phím 3 mode",
            [
                PeripheralConnection.wired,
                PeripheralConnection.wireless_2_4,
                PeripheralConnection.bluetooth,
            ],
        ),
        (
            "chuột wireless/bluetooth",
            [PeripheralConnection.wireless_2_4, PeripheralConnection.bluetooth],
        ),
        ("chuột không dây | bluetooth", [PeripheralConnection.bluetooth]),
        ("chuột logitech g502 lightspeed", [PeripheralConnection.wireless_2_4]),
    ],
)
def test_peripheral_connection_reads_only_what_is_written(
    text: str, expected: list[PeripheralConnection]
) -> None:
    assert peripheral_connection(text) == expected


@pytest.mark.parametrize("text", ["chuột logitech g102", "bàn phím cơ aula f75", ""])
def test_peripheral_connection_is_none_without_evidence(text: str) -> None:
    assert peripheral_connection(text) is None


def test_usb_receiver_is_radio_not_a_cable() -> None:
    found = read_connectivity(fold("Kết nối: Cổng USB, USB Receiver"))
    assert found.radio and found.usb  # "Cổng USB" vẫn là USB; receiver không bị tính là cáp
    assert not read_connectivity(fold("USB Receiver")).usb


def test_jack_and_usb_cable_are_distinct() -> None:
    assert read_connectivity(fold("Jack 3.5 mm")).jack
    assert read_connectivity(fold("Razer Kraken V3 X USB")).usb
    assert not read_connectivity(fold("Razer Kraken V3 X USB")).radio
