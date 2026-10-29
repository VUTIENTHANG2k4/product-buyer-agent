"""Bộ trích xuất thông số chuột, bàn phím, tai nghe theo luật."""

from typing import Any

import pytest

from app.normalize.specs.headset import extract_headset
from app.normalize.specs.keyboard import extract_keyboard
from app.normalize.specs.mouse import extract_mouse


def mouse(title: str, raw: dict[str, str] | None = None) -> dict[str, Any]:
    return extract_mouse(title, raw or {}).model_dump(mode="json", exclude_none=True)


def keyboard(title: str, raw: dict[str, str] | None = None) -> dict[str, Any]:
    return extract_keyboard(title, raw or {}).model_dump(mode="json", exclude_none=True)


def headset(title: str, raw: dict[str, str] | None = None) -> dict[str, Any]:
    return extract_headset(title, raw or {}).model_dump(mode="json", exclude_none=True)


# ---- chuột ----
@pytest.mark.parametrize(
    ("title", "connection"),
    [
        ("Chuột gaming không dây Logitech G304 X Superlight Black", ["wireless_2_4"]),
        ("Chuột Logitech G502 Lightspeed Wireless Black", ["wireless_2_4"]),
        ("Chuột Bluetooth Silent Rapoo M650 Lucky Cat", ["bluetooth"]),
        (
            "Chuột Logitech SIGNATURE M650 Wireless/Bluetooth - màu đen",
            ["wireless_2_4", "bluetooth"],
        ),
        ("Chuột có dây Logitech G102", ["wired"]),
    ],
)
def test_mouse_connection_from_the_title(title: str, connection: list[str]) -> None:
    assert mouse(title)["connection"] == connection


@pytest.mark.parametrize(
    "title", ["Chuột Logitech G102 Gen2 LightSync", "Chuột Pulsar X2 Mini Black", "Chuột ATK X1 V2"]
)
def test_mouse_connection_is_not_guessed_from_a_bare_model_name(title: str) -> None:
    assert "connection" not in mouse(title)


def test_mouse_connection_label_beats_the_generic_wireless_word() -> None:
    specs = mouse(
        "Chuột không dây Elecom M-IR07DR",
        {"Trọng lượng": "52 g", "Chuẩn kết nối": "Bluetooth", "Độ phân giải": "1200 dpi"},
    )
    assert specs == {"connection": ["bluetooth"], "weight_g": 52, "dpi_max": 1200}


def test_mouse_detail_table_of_a_gearvn_mouse() -> None:
    specs = mouse(
        "Chuột gaming không dây Logitech Pro X3 Superstrike Lightspeed Black",
        {
            "Kết nối": "Cổng USB, USB Receiver",
            "Cảm biến (Sensor)": "Logitech HERO 2",
            "Độ phân giải (DPI)": "48000 DPI",
            "Polling Rate": "8000 Hz",
            "Trọng lượng": "59 g",
        },
    )
    assert specs == {
        "connection": ["wireless_2_4"],
        "dpi_max": 48000,
        "sensor": "Logitech HERO 2",
        "weight_g": 59,
    }


def test_mouse_dpi_takes_the_highest_value_and_ignores_polling_rate() -> None:
    assert mouse("Chuột X 800 DPI / 26000 DPI 1000 Hz")["dpi_max"] == 26000


@pytest.mark.parametrize(
    ("title", "shape"),
    [
        ("Chuột công thái học E-Dra EM605W White", "ergo_right"),
        ("Chuột Logitech Lift Vertical Ergonomic", "ergo_right"),
        ("Chuột đối xứng Rapoo", "ambidextrous"),
    ],
)
def test_mouse_shape(title: str, shape: str) -> None:
    assert mouse(title)["shape"] == shape


def test_mouse_rgb_from_title_or_light_label() -> None:
    assert mouse("Chuột Rapoo Gaming V280 RGB")["rgb"] is True
    assert mouse("Chuột X", {"Đèn chuột": "có, RGB 16.8 triệu màu"})["rgb"] is True
    assert "rgb" not in mouse("Chuột X")


def test_mouse_implausible_weight_is_dropped() -> None:
    assert "weight_g" not in mouse("Chuột X", {"Trọng lượng": "5 g"})


# ---- bàn phím ----
@pytest.mark.parametrize(
    ("title", "switch_type"),
    [
        ("Bàn phím cơ AULA F75 Milk White switch", "mechanical"),
        ("Bàn phím Logitech G316 X 98 RGB Trắng Tactile", "mechanical"),
        ("Bàn phím cơ ASUS ROG Falchion Ace 75 HE V2 White", "magnetic"),
        ("Bàn phím gaming ASUS ROG Azoth 96 HE Black", "magnetic"),
        ("Bàn phím cơ Logitech G512 X 98 TMR Tactile switch", "magnetic"),
        ("Bàn phím quang Razer Huntsman V3 Optical", "optical"),
        ("Bàn phím giả cơ Rapoo V500", "membrane"),
    ],
)
def test_keyboard_switch_type(title: str, switch_type: str) -> None:
    assert keyboard(title)["switch_type"] == switch_type


@pytest.mark.parametrize(
    "title", ["Bàn phím không dây HyperWork Core Type CT01 Đen", "Bàn phím DareU LK135"]
)
def test_keyboard_switch_type_is_not_guessed_without_evidence(title: str) -> None:
    assert "switch_type" not in keyboard(title)


def test_hertz_word_he_is_only_hall_effect_in_uppercase() -> None:
    assert "switch_type" not in keyboard("Bàn phím he thong Rapoo")


@pytest.mark.parametrize(
    ("title", "form"),
    [
        ("Bàn phím cơ AULA F75 Black", "75"),
        ("Bàn phím cơ DareU Flex 75 White Black", "75"),
        ("Bàn phím cơ Logitech G515 LightSpeed TKL", "tkl"),
        ("Bàn phím cơ Razer Reclusa X Mini 65%", "65"),
        ("Bàn phím cơ AULA H108 White", "full"),
        ("Bàn phím cơ Logitech G316 X 98 White", "other"),
        ("Bàn phím gaming ASUS ROG Azoth 96 HE", "other"),
    ],
)
def test_keyboard_form_factor(title: str, form: str) -> None:
    assert keyboard(title)["form_factor"] == form


def test_keyboard_form_factor_ignores_model_numbers_with_letters_after_digits() -> None:
    assert "form_factor" not in keyboard("Bàn phím cơ Logitech K98M")
    assert "form_factor" not in keyboard("Bàn phím cơ E-DRA EK375W White")


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Bàn phím cơ AULA F75 Grey White Milk White switch", "Milk White"),
        ("Bàn phím cơ DareU FLEX 75 White Black Pegasus switch", "Pegasus"),
        ("Bàn phím cơ Logitech G512 X 98 White Tactile switch", "Tactile"),
        ("Bàn phím cơ Logitech G515 LightSpeed TKL Wireless Tactile switch", "Tactile"),
        ("Bàn phím cơ ATK RS6 Air Pink Iceblade switch", "Iceblade"),
        ("Bàn phím cơ AULA H108 White Black Silent Cotton Candy Switch", "Cotton Candy"),
        ("Bàn phím cơ DareU Flex 75 White Black 3 Mode Pegasus switch", "Pegasus"),
    ],
)
def test_keyboard_switch_name_drops_colours_and_connection_words(title: str, name: str) -> None:
    assert keyboard(title)["switch_name"] == name


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Bàn phím E-Dra EK387 Pro Huano Switch", "Huano"),
        ("Bàn phím cơ Asus ROG Falchion Ace 75 HE Black HFX V2 switch", "HFX V2"),
        ("Bàn phím cơ AKKO 5075B Plus V3 Switch", None),
        ("Bàn phím Keychron K8 Pro Hotswap Switch", None),
        ("Bàn phím cơ Hot-swap switch", None),
        ("Bàn phím Pro Switch Gateron", None),
    ],
)
def test_keyboard_switch_name_skips_model_line_words_and_bare_versions(
    title: str, name: str | None
) -> None:
    # T5.4: "Pro/Plus/Hotswap" và phiên bản đứng riêng ("V3") không phải tên switch; chữ có dấu
    # ("phím") không còn bị cắt thành "m".
    assert keyboard(title).get("switch_name") == name


def test_keyboard_multi_mode_means_wired_radio_and_bluetooth() -> None:
    assert keyboard("Bàn phím cơ AULA F75 3 Mode Iced Berry")["connection"] == [
        "wired",
        "wireless_2_4",
        "bluetooth",
    ]


def test_keyboard_hot_swap_and_backlight() -> None:
    specs = keyboard("Bàn phím cơ hot-swap RGB AULA F75")
    assert specs["hot_swap"] is True
    assert specs["backlight"] == "rgb"


def test_keyboard_backlight_from_label() -> None:
    assert keyboard("Bàn phím cơ X", {"Đèn nền": "LED RGB 16,8 triệu màu"})["backlight"] == "rgb"
    assert keyboard("Bàn phím cơ X", {"Đèn nền": "Một màu trắng"})["backlight"] == "single"
    assert keyboard("Bàn phím cơ X", {"Đèn nền": "Không"})["backlight"] == "none"


# ---- tai nghe ----
@pytest.mark.parametrize(
    ("title", "form"),
    [
        ("Tai nghe HyperX Cloud Earbuds III Black", "in_ear"),
        ("Tai nghe True Wireless Blaupunkt LITE ONE", "tws"),
        ("Tai nghe TWS Anker Soundcore", "tws"),
        ("Tai nghe chụp tai Sony WH-1000XM5", "over_ear"),
        ("Tai nghe over-ear Corsair", "over_ear"),
        ("Tai nghe on-ear JBL Tune 520BT", "on_ear"),
    ],
)
def test_headset_form(title: str, form: str) -> None:
    assert headset(title)["form"] == form


@pytest.mark.parametrize(
    "title", ["Tai nghe HyperX Cloud III Black", "Tai nghe Razer BlackShark V3 White"]
)
def test_headset_form_and_connection_are_not_guessed_from_a_bare_model_name(title: str) -> None:
    assert headset(title) == {}


@pytest.mark.parametrize(
    ("title", "raw", "connection"),
    [
        ("Tai nghe Razer Kraken V3 X USB", {}, ["usb"]),
        ("Tai nghe Logitech G321 LightSpeed White", {}, ["wireless_2_4"]),
        ("Tai nghe E-Dra EH497W Triple Mode", {}, ["usb", "wireless_2_4", "bluetooth"]),
        ("Tai nghe Corsair HS50", {"Cổng giao tiếp/Cổng sạc": "Jack 3.5 mm"}, ["wired_3_5"]),
        (
            "Tai nghe Logitech G Pro X3",
            {"Hỗ trợ 3 kết nối": "Không dây LightSpeed 2.4Ghz, Bluetooth và có dây (3.5mm)"},
            ["wired_3_5", "wireless_2_4", "bluetooth"],
        ),
    ],
)
def test_headset_connection(title: str, raw: dict[str, str], connection: list[str]) -> None:
    assert headset(title, raw)["connection"] == connection


def test_headset_extras() -> None:
    specs = headset(
        "Tai nghe gaming 7.1 chống ồn chủ động driver 50mm",
        {"Micro": "Có, tháo rời"},
    )
    assert specs["surround_7_1"] is True
    assert specs["anc"] is True
    assert specs["driver_mm"] == 50
    assert specs["has_mic"] is True


def test_headset_mic_label_negative() -> None:
    assert headset("Tai nghe X", {"Micro": "Không"})["has_mic"] is False


def test_headset_cable_length_is_not_a_driver_size() -> None:
    assert "driver_mm" not in headset("Tai nghe X jack 3.5mm")


def test_headset_chong_on_label_alone_is_not_anc() -> None:
    assert "anc" not in headset("Tai nghe Corsair HS50 PRO Stereo", {"Tính năng": "Chống ồn"})


@pytest.mark.parametrize(
    ("title", "raw"),
    [
        ("Tai nghe HyperX Cloud Flight 2 Wireless", {}),  # "không dây" trơn: chưa biết 2.4G hay BT
        ("Tai nghe Apple AirPods Pro 2 USB-C", {}),  # USB-C là cổng sạc
        ("Tai nghe Sony WH-1000XM5", {"Cổng sạc": "USB Type-C"}),
        ("Tai nghe Sony WH-1000XM5", {"Công nghệ âm thanh": "USB DAC"}),
    ],
)
def test_headset_connection_is_left_empty_when_the_text_does_not_say(
    title: str, raw: dict[str, str]
) -> None:
    assert headset(title, raw).get("connection") is None


def test_true_wireless_earbuds_are_bluetooth_not_2_4g() -> None:
    specs = headset("Tai nghe Sony WF-C700N True Wireless")
    assert (specs["form"], specs["connection"]) == ("tws", ["bluetooth"])


def test_headset_with_explicit_dongle_is_2_4g() -> None:
    assert headset("Tai nghe HyperX Cloud Flight 2 Wireless 2.4GHz")["connection"] == [
        "wireless_2_4"
    ]


@pytest.mark.parametrize(
    ("text", "dpi"),
    [
        ("Up to 25,600 DPI", 25600),
        ("12.000 DPI", 12000),
        ("35,000 DPI", 35000),
        ("26000 DPI / 800 DPI", 26000),
    ],
)
def test_mouse_dpi_reads_thousands_separators(text: str, dpi: int) -> None:
    assert mouse("Chuột Foo Bar", {"Độ phân giải": text})["dpi_max"] == dpi


@pytest.mark.parametrize(
    ("title", "form_factor"),
    [
        ("Bàn phím Corsair K60 RGB Pro", None),  # K60 là tên mẫu (full-size), không phải 60%
        ("Bàn phím MSI Vigor GK60", None),
        ("Bàn phím Corsair K65 RGB Mini 60%", "60"),
        ("Bàn phím cơ AULA F75 Pro", "75"),
    ],
)
def test_keyboard_form_factor_ignores_model_names_that_contain_a_number(
    title: str, form_factor: str | None
) -> None:
    assert keyboard(title).get("form_factor") == form_factor
