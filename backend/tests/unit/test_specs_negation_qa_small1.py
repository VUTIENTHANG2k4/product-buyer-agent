"""QA small-1: phủ định, khối lượng và số nút trong bộ trích xuất thông số (T5.7).

Test `xfail(strict=True)` là lỗi đã tái hiện (mã BUG-S1-n); khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import pytest

from app.normalize.specs.headset import extract_headset
from app.normalize.specs.keyboard import extract_keyboard
from app.normalize.specs.mouse import extract_mouse
from app.normalize.specs.parsing import parse_grams_all
from app.normalize.specs.types import HeadsetConnection, PeripheralConnection

WIRED = PeripheralConnection.wired
RADIO = PeripheralConnection.wireless_2_4
BT = PeripheralConnection.bluetooth


def bug(code: str, why: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{code}: {why}")


# ---- mic ----
@pytest.mark.parametrize(
    "title",
    [
        "Tai nghe không có mic",
        "Tai nghe KHÔNG CÓ MIC",
        "Tai nghe Không Có Mic",
        "Tai nghe khong co mic",
        "Tai nghe không có mic",
        "Tai nghe không kèm mic",
        "Tai nghe không có micro",
        "Tai nghe không có microphone",
        "Tai nghe không mic",
        "Tai nghe NO MIC",
        "Tai nghe without mic",
        "Tai nghe không tích hợp mic",
        "Tai nghe không (có) mic",
    ],
)
def test_negated_mic_is_not_reported_as_having_a_mic(title: str) -> None:
    assert extract_headset(title, {}).has_mic is None


@pytest.mark.parametrize(
    "title",
    [
        "Tai nghe có mic",
        "Tai nghe kèm mic",
        "Tai nghe with microphone",
        "Tai nghe không dây kèm mic",
        "Tai nghe không dây có mic",
        "Tai nghe có mic, không có mic rời",
        "Tai nghe không có mic rời, có mic",
        "Tai nghe không, có mic",
    ],
)
def test_affirmed_mic_survives_a_negation_elsewhere_in_the_title(title: str) -> None:
    assert extract_headset(title, {}).has_mic is True


@pytest.mark.parametrize(
    "title", ["Tai nghe ko có mic", "Tai nghe k có mic", "Tai nghe chưa có mic"]
)
def test_abbreviated_negations_of_the_mic_are_not_a_mic(title: str) -> None:
    assert extract_headset(title, {}).has_mic is not True


@pytest.mark.parametrize("value", ["Noise Cancelling boom", "Noise-cancelling mic"])
def test_a_micro_label_that_merely_starts_with_no_is_not_a_negation(value: str) -> None:
    assert extract_headset("Tai nghe X", {"Micro": value}).has_mic is not False


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Có", True), ("Không", False), ("Không có", False), ("No", False), ("N/A", False)],
)
def test_micro_label_values(value: str, expected: bool) -> None:
    assert extract_headset("Tai nghe X", {"Micro": value}).has_mic is expected


# ---- ANC ----
@pytest.mark.parametrize(
    "title",
    [
        "Tai nghe không ANC",
        "Tai nghe không có ANC",
        "Tai nghe No ANC",
        "Tai nghe KHÔNG CÓ ANC",
        "Tai nghe không có chống ồn chủ động",
        "Tai nghe không có noise cancelling",
        "Tai nghe without noise cancelling",
        "Tai nghe không có Active Noise Cancelling",
        "Tai nghe không chống ồn",
    ],
)
def test_negated_anc_is_not_reported(title: str) -> None:
    assert extract_headset(title, {}).anc is None


@pytest.mark.parametrize(
    "title", ["Tai nghe ANC", "Tai nghe chống ồn chủ động ANC", "Tai nghe ANC, không có mic"]
)
def test_affirmed_anc_is_reported(title: str) -> None:
    assert extract_headset(title, {}).anc is True


@pytest.mark.parametrize(
    "title",
    [
        "Tai nghe không hỗ trợ ANC",
        "Tai nghe không tích hợp ANC",
        "Tai nghe không hỗ trợ chống ồn chủ động",
        "Tai nghe chưa có ANC",
        "Tai nghe Non-ANC",
        "Tai nghe NO-ANC",
        "Tai nghe w/o ANC",
        "Tai nghe ko ANC",
    ],
)
def test_wordier_negations_of_anc_are_not_reported(title: str) -> None:
    assert extract_headset(title, {}).anc is None


# ---- kết nối ----
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Chuột không có dây", [RADIO]),
        ("Chuột KHÔNG CÓ DÂY", [RADIO]),
        ("Chuột Không Có Dây", [RADIO]),
        ("Chuột không có dây bluetooth", [BT]),
        ("Chuột wireless không bluetooth", [RADIO]),
        ("Chuột wireless no bluetooth", [RADIO]),
        ("Chuột không dây không có bluetooth", [RADIO]),
        ("Chuột 2.4G không Bluetooth", [RADIO]),
        ("Chuột 2.4G wireless USB, no Bluetooth", [RADIO]),
        ("Chuột Bluetooth không 2.4G", [BT]),
        ("Chuột không dây không bluetooth không 2.4G", [RADIO]),
        ("Chuột có dây USB không Bluetooth", [WIRED]),
        ("Chuột không Bluetooth", None),
        ("Chuột Bluetooth không", [BT]),
        ("Chuột có dây", [WIRED]),
        ("Chuột 3 mode 2.4G Bluetooth", [WIRED, RADIO, BT]),
    ],
)
def test_mouse_connection_with_negations(
    title: str, expected: list[PeripheralConnection] | None
) -> None:
    assert extract_mouse(title, {}).connection == expected


def test_a_keyboard_uses_the_same_negation_rules() -> None:
    assert extract_keyboard("Bàn phím cơ không dây không Bluetooth", {}).connection == [RADIO]
    assert extract_keyboard("Bàn phím cơ không có dây", {}).connection == [RADIO]


@pytest.mark.parametrize(
    "title",
    [
        "Chuột wireless không hỗ trợ bluetooth",
        "Chuột wireless chưa hỗ trợ bluetooth",
        "Chuột wireless No-Bluetooth",
        "Chuột wireless w/o Bluetooth",
        "Chuột không dây ko bluetooth",
    ],
)
def test_wordier_negations_of_bluetooth_do_not_turn_wireless_into_bluetooth(title: str) -> None:
    assert extract_mouse(title, {}).connection == [RADIO]


@pytest.mark.parametrize(
    "title",
    [
        "Tai nghe over-ear không có jack 3.5mm",
        "Tai nghe over-ear không jack 3.5mm",
        "Tai nghe over-ear Bluetooth không 3.5mm",
        "Tai nghe over-ear Bluetooth không cổng 3.5mm",
        "Tai nghe over-ear USB, no 3.5mm",
    ],
)
def test_a_negated_3_5mm_jack_is_not_a_wired_connection(title: str) -> None:
    connection = extract_headset(title, {}).connection

    assert HeadsetConnection.wired_3_5 not in (connection or [])


def test_headset_connection_keeps_the_jack_when_it_is_affirmed() -> None:
    connection = extract_headset("Tai nghe over-ear Bluetooth, jack 3.5mm", {}).connection

    assert connection == [HeadsetConnection.wired_3_5, HeadsetConnection.bluetooth]


# ---- khối lượng chuột ----
@pytest.mark.parametrize(
    ("title", "raw", "grams"),
    [
        ("Chuột 2.4G 99g", {}, 99),
        ("Chuột 99g 2.4G", {}, 99),
        ("Chuột Bluetooth 5.0 2.4G 63 g", {}, 63),
        ("Chuột 2.4G Wireless 0.1kg", {}, 100),
        ("Chuột", {"Trọng lượng": "0.1kg"}, 100),
        ("Chuột", {"Trọng lượng": "2.4G 99g"}, 99),
        ("Chuột 2.4G 80g", {"Trọng lượng": "50 kg"}, 80),
        ("Chuột", {"Trọng lượng": "1.2 kg / 80g"}, 80),
        ("Chuột", {"Trọng lượng": "63g (không cáp), 80g (có cáp)"}, 63),
        ("Chuột 0,06kg", {}, 60),
        ("Chuột 99,5g", {}, 100),
        ("Chuột 20 g", {}, 20),
        ("Chuột 300g", {}, 300),
        ("Chuột 5kg", {}, None),
        ("Chuột", {"Trọng lượng": "5kg"}, None),
        ("Chuột 19g", {}, None),
        ("Chuột 301g", {}, None),
        ("Chuột 0g 60g", {}, 60),
        ("Chuột 0.00001kg", {}, None),
        ("Chuột 1e3g", {}, None),
        ("Chuột " + "9" * 5000 + "g", {}, None),
    ],
)
def test_mouse_weight_reads_every_gram_value_and_keeps_the_plausible_one(
    title: str, raw: dict[str, str], grams: int | None
) -> None:
    assert extract_mouse(title, raw).weight_g == grams


def test_parse_grams_all_returns_values_in_order_and_skips_non_positive() -> None:
    assert parse_grams_all("2.4G 99g 0.1kg 0g") == [2, 99, 100]
    assert parse_grams_all("không có khối lượng") == []
    assert parse_grams_all("") == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG-S1-13: gia tốc cảm biến '50G' (đơn vị G) đứng trước khối lượng được đọc thành 50 gam; "
        "weight_g lấy giá trị hợp lý đầu tiên mà không phân biệt 'G' lực với gam"
    ),
)
def test_sensor_acceleration_in_g_force_is_not_the_weight() -> None:
    assert extract_mouse("Chuột Razer Viper V3 Pro 8K 35K DPI 50G 54g", {}).weight_g == 54


# ---- số nút ----
@pytest.mark.parametrize(
    ("value", "buttons"),
    [
        ("6", 6),
        ("6 nút", 6),
        ("12+2", 12),
        ("7 nút (5 lập trình)", 7),
        ("99", 99),
        ("1", 1),
        ("0", None),
        ("100", None),
        ("99999", None),
        ("9" * 5000, None),
        ("", None),
        ("nhiều nút", None),
    ],
)
def test_mouse_button_count_bounds(value: str, buttons: int | None) -> None:
    assert extract_mouse("Chuột X", {"Số nút": value}).buttons == buttons
