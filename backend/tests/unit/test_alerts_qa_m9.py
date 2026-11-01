"""QA M9: biên của luật cảnh báo, thông báo (Telegram, email), cấu hình cục bộ và parse_detail."""

import json
import smtplib
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.domain.enums import AlertStatus, PriceType, SiteKey, StockStatus
from app.scrapers.parsing import schema_price, schema_stock
from app.scrapers.sites.anphat import AnPhatScraper
from app.scrapers.sites.fptshop import FptShopScraper
from app.scrapers.sites.gearvn import GearVNScraper
from app.services.alert_service import MAX_TARGET_PRICE, should_notify
from app.services.notifier.base import NotificationFailed
from app.services.notifier.email import EmailNotifier
from app.services.notifier.message import format_vnd, render_alert_message
from app.services.notifier.telegram import TelegramNotifier
from tests.factories import make_price_alert
from tests.fakes import FakeFetcher

TOKEN = "123456:MOCK-TOKEN"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


# ---- should_notify: biên số nguyên ------------------------------------------------------------
def test_price_equal_to_the_largest_storable_target_still_fires_without_overflow() -> None:
    alert = make_price_alert(1, target_price=MAX_TARGET_PRICE)

    assert should_notify(alert, MAX_TARGET_PRICE) is True
    assert should_notify(alert, MAX_TARGET_PRICE + 1) is False


def test_renotify_threshold_is_exact_for_prices_near_bigint() -> None:
    last = MAX_TARGET_PRICE - MAX_TARGET_PRICE % 100  # chia hết cho 100: 99% là số nguyên
    alert = make_price_alert(
        1, target_price=MAX_TARGET_PRICE, status=AlertStatus.triggered, last_notified_price=last
    )
    one_percent_lower = last // 100 * 99

    assert should_notify(alert, one_percent_lower) is True
    assert should_notify(alert, one_percent_lower + 1) is False


@pytest.mark.parametrize(
    ("last", "price", "expected"),
    [
        (1, 1, False),  # cùng một mức không bao giờ gửi lại
        (99, 98, True),  # giảm 1,01% (9.800 <= 9.801)
        (100, 99, True),  # đúng 1%
        (100, 100, False),
        (101, 100, False),  # giảm 0,99%
        (200, 198, True),
    ],
)
def test_small_notified_prices_follow_the_exact_integer_one_percent_rule(
    last: int, price: int, expected: bool
) -> None:
    alert = make_price_alert(
        1, target_price=1_000, status=AlertStatus.triggered, last_notified_price=last
    )

    assert should_notify(alert, price) is expected


# ---- nội dung thông báo -----------------------------------------------------------------------
@pytest.mark.parametrize("amount", [0, 999, 1_000, 1_234_567, 2**63 - 1])
def test_format_vnd_groups_thousands_with_dots_for_any_size(amount: int) -> None:
    text = format_vnd(amount)

    assert text.endswith(" ₫")
    assert text[: -len(" ₫")].replace(".", "") == str(amount)
    assert all(len(group) == 3 for group in text[: -len(" ₫")].split(".")[1:])


def test_message_keeps_vietnamese_marks_emoji_and_very_long_names_intact() -> None:
    name = "Laptop Gaming 🔥 Nguyễn Tiến Đạt " + "x" * 3_000

    message = render_alert_message(
        product_name=name,
        price=27_490_000,
        target_price=28_000_000,
        site=SiteKey.gearvn,
        url="https://gearvn.com/products/a?x=1&y=ộ",
    )

    assert name in message.body
    assert "\n" not in message.subject and name.split()[0] in message.subject
    assert message.body.endswith("Link: https://gearvn.com/products/a?x=1&y=ộ")


# ---- Telegram ---------------------------------------------------------------------------------
def telegram() -> TelegramNotifier:
    return TelegramNotifier(SecretStr(TOKEN))


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"ok": False, "description": "Bad Request: chat not found"}),
        httpx.Response(200, text="<html>Đăng nhập Wi-Fi công cộng</html>"),
        httpx.Response(200, text=""),
        httpx.Response(200, json=["ok"]),
    ],
    ids=["ok-false", "html-from-a-proxy", "empty-body", "json-list"],
)
def test_http_200_without_ok_true_is_not_a_successful_delivery(response: httpx.Response) -> None:
    """BUG-M9-1: 200 mà thân không phải `{"ok": true}` bị coi là đã gửi nên cảnh báo thành
    `triggered` dù người dùng không nhận tin (proxy/captive portal trả 200 trang đăng nhập)."""
    respx.post(URL).mock(return_value=response)

    with pytest.raises(NotificationFailed):
        telegram().send("1", "s", "b")


@respx.mock
def test_negative_supergroup_chat_id_and_unicode_text_are_sent_verbatim() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    telegram().send("-1001234567890", "Giá giảm 🔥", "Nguyễn Văn Ạ")

    assert json.loads(route.calls[0].request.content) == {
        "chat_id": "-1001234567890",
        "text": "Giá giảm 🔥\n\nNguyễn Văn Ạ",
    }


@respx.mock
def test_a_token_with_a_control_character_fails_cleanly_without_leaking_it() -> None:
    """BUG-M9-2: `httpx.InvalidURL` không phải `HTTPError` nên thoát khỏi notifier thành lỗi lạ."""
    bad = TelegramNotifier(SecretStr("123456:MOCK\nTOKEN"))

    with pytest.raises(NotificationFailed) as error:
        bad.send("1", "s", "b")

    assert "MOCK" not in str(error.value)


@respx.mock
def test_truncation_never_splits_a_surrogate_pair_or_exceeds_the_limit() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    telegram().send("1", "s", "🔥" * 5_000)

    sent = json.loads(route.calls[0].request.content)["text"]
    assert len(sent) == 4096 and set(sent[3:]) == {"🔥"}


# ---- email ------------------------------------------------------------------------------------
class RecordingSMTP:
    instances: list["RecordingSMTP"] = []

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.messages: list[EmailMessage] = []
        self.logins: list[tuple[str, str]] = []
        self.kind = type(self).__name__
        RecordingSMTP.instances.append(self)

    def __enter__(self) -> "RecordingSMTP":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, **kwargs: Any) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        self.logins.append((user, password))

    def send_message(self, message: EmailMessage) -> None:
        self.messages.append(message)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[RecordingSMTP]:
    RecordingSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", RecordingSMTP)
    return RecordingSMTP


def email_notifier(**overrides: Any) -> EmailNotifier:
    config: dict[str, Any] = {
        "host": "smtp.mock.example",
        "port": 587,
        "sender": "alerts@mock.example",
    }
    return EmailNotifier(**{**config, **overrides})


def test_vietnamese_subject_and_body_survive_a_real_mime_round_trip(
    smtp: type[RecordingSMTP],
) -> None:
    email_notifier().send(
        "buyer@mock.example", "Giá giảm: Chuột Lô-gi-tếch 🔥 còn 1.000 ₫", "Nội dung có dấu: ộ ữ"
    )

    (message,) = smtp.instances[0].messages
    parsed = message_from_bytes(message.as_bytes(), policy=policy.default)
    assert parsed["Subject"] == "Giá giảm: Chuột Lô-gi-tếch 🔥 còn 1.000 ₫"
    assert parsed.get_content().strip() == "Nội dung có dấu: ộ ữ"


def test_a_very_long_subject_is_folded_into_a_valid_message(smtp: type[RecordingSMTP]) -> None:
    subject = "Giá giảm: " + " ".join(["Laptop"] * 600)

    email_notifier().send("buyer@mock.example", subject, "b")

    (message,) = smtp.instances[0].messages
    lines = message.as_bytes().replace(b"\r\n", b"\n").split(b"\n")
    assert max(len(line) for line in lines) <= 998  # giới hạn dòng của RFC 5322


@pytest.mark.parametrize(
    "destination",
    ["a@mock.example\nBcc: x@y.z", "a@mock.example\rBcc: x@y.z"],
)
def test_control_characters_in_the_destination_never_reach_the_smtp_server(
    smtp: type[RecordingSMTP], destination: str
) -> None:
    with pytest.raises(NotificationFailed):
        email_notifier().send(destination, "s", "b")

    assert not smtp.instances or all(not s.messages for s in smtp.instances)


def test_a_sender_with_a_line_break_is_a_failed_send_not_an_injected_header(
    smtp: type[RecordingSMTP],
) -> None:
    with pytest.raises(NotificationFailed):
        email_notifier(sender="a@mock.example\r\nBcc: x@y.z").send("b@mock.example", "s", "b")

    assert smtp.instances == []


def test_password_without_a_user_does_not_attempt_a_login(smtp: type[RecordingSMTP]) -> None:
    email_notifier(user="", password=SecretStr("lonely")).send("b@mock.example", "s", "b")

    assert smtp.instances[0].logins == []


def test_non_ascii_destination_is_reported_as_a_failed_send_not_a_crash(
    smtp: type[RecordingSMTP],
) -> None:
    class Strict(RecordingSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPNotSupportedError("SMTPUTF8 not supported")

    smtplib.SMTP = Strict  # type: ignore[misc,assignment]
    try:
        with pytest.raises(NotificationFailed):
            email_notifier().send("nguyễn@mock.example", "s", "b")
    finally:
        smtplib.SMTP = RecordingSMTP  # type: ignore[misc]


# ---- cấu hình cục bộ (LOCAL_HOSTS) ------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "http://MOCK-SHOP:8100",  # tên host không phân biệt hoa/thường
        "http://mock-shop",
        "https://mock-shop:8443/",
        "http://[::1]",
        "http://LOCALHOST:1",
    ],
)
def test_mock_shop_url_accepts_local_hosts_in_any_case_with_or_without_port(url: str) -> None:
    assert Settings(mock_shop_url=url).mock_shop_url == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://mock-shop.:8100",  # dấu chấm cuối là tên miền tuyệt đối, không còn là nhãn đơn
        "http://mock-shop.com",
        "http://mock_shop:8100",
        "http://mock-shop@evil.example",
        "http://mock-shop:80@evil.example:8100",
        "http://mock-shop%2eevil.example",
        "http://mock‐shop:8100",
        "http://[::2]",
        "http://127.0.0.2",
        "http://0.0.0.0:8100",
    ],
)
def test_mock_shop_url_rejects_lookalike_and_non_loopback_hosts(url: str) -> None:
    with pytest.raises(ValidationError, match="mock_shop_url"):
        Settings(mock_shop_url=url)


# ---- parse_detail: dữ liệu bẩn ----------------------------------------------------------------
def product_page(offers: Any, extra: str = "") -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Mock",
        "offers": offers,
    }
    return (
        "<html><body><h1>Mock</h1>"
        f'<script type="application/ld+json">{json.dumps(payload)}</script>{extra}</body></html>'
    )


SCRAPERS = [GearVNScraper, FptShopScraper, AnPhatScraper]
DOMAINS = {
    GearVNScraper: "https://gearvn.com/products/x",
    FptShopScraper: "https://fptshop.com.vn/may-tinh-xach-tay/x",
    AnPhatScraper: "https://www.anphatpc.com.vn/x.html",
}


def detail(scraper_type: Any, html: str) -> Any:
    return scraper_type(FakeFetcher({})).parse_detail(html, DOMAINS[scraper_type])


@pytest.mark.parametrize("scraper_type", SCRAPERS)
@pytest.mark.parametrize(
    "offers",
    [
        [],
        {},
        None,
        "InStock",
        [None, 5, "x"],
        {"price": None},
        {"price": -27_490_000},
        {"price": 0},
        {"price": 9_999},
        {"price": 500_000_001},
        {"price": "Liên hệ"},
        {"price": True},
        {"price": [27_490_000]},
        {"price": {"value": 27_490_000}},
        {"price": 27_490_000.5},
        {"price": float("1e400")},
    ],
)
def test_unusable_json_ld_prices_give_no_price_instead_of_a_wrong_one(
    scraper_type: Any, offers: Any
) -> None:
    result = detail(scraper_type, product_page(offers).replace("Infinity", "1e999"))

    assert result.price is None
    assert result.price_type is PriceType.unknown or scraper_type is AnPhatScraper


@pytest.mark.parametrize("scraper_type", SCRAPERS)
@pytest.mark.parametrize("html", ["", "   ", "<html></html>", "\x00\x00", "<script", "{" * 5_000])
def test_pages_without_any_usable_markup_parse_to_an_empty_detail(
    scraper_type: Any, html: str
) -> None:
    result = detail(scraper_type, html)

    assert (result.price, result.list_price, result.stock_status) == (
        None,
        None,
        StockStatus.unknown,
    )


@pytest.mark.parametrize("scraper_type", SCRAPERS)
def test_broken_json_ld_block_does_not_hide_a_valid_one_after_it(scraper_type: Any) -> None:
    good = product_page({"price": 27_490_000, "availability": "https://schema.org/InStock"})
    html = good.replace(
        "</body>", '<script type="application/ld+json">{not json</script></body>'
    ).replace("<h1>", '<script type="application/ld+json">{oops</script><h1>')

    assert detail(scraper_type, html).price == 27_490_000


def test_gearvn_price_specification_with_several_entries_picks_the_strikethrough() -> None:
    offers = {
        "price": 19_990_000,
        "priceSpecification": [
            {"priceType": "https://schema.org/SalePrice", "price": 19_990_000},
            {"priceType": "https://schema.org/StrikethroughPrice", "price": 24_990_000},
            {"priceType": "https://schema.org/StrikethroughPrice", "price": 29_990_000},
        ],
    }

    result = detail(GearVNScraper, product_page(offers))

    assert (result.price, result.list_price, result.price_type) == (
        19_990_000,
        24_990_000,
        PriceType.sale,
    )


def test_gearvn_strikethrough_price_out_of_the_valid_range_is_ignored() -> None:
    offers = {
        "price": 19_990_000,
        "priceSpecification": {
            "priceType": "https://schema.org/StrikethroughPrice",
            "price": 9_000_000_000,
        },
    }

    result = detail(GearVNScraper, product_page(offers))

    assert (result.price, result.list_price, result.price_type) == (
        19_990_000,
        None,
        PriceType.regular,
    )


def test_fptshop_without_json_ld_has_neither_price_nor_a_guessed_price_type() -> None:
    html = '<html><body><h1>Máy</h1><p class="line-through">30.000.000đ</p><p>27.490.000đ</p>'

    result = detail(FptShopScraper, html)

    assert (result.price, result.list_price, result.price_type) == (None, None, PriceType.unknown)


def test_fptshop_struck_price_of_a_related_product_is_not_taken_as_this_products_list_price() -> (
    None
):
    related = (
        '<section><div><p class="line-through">40.000.000đ</p><p>35.000.000đ</p></div></section>'
    )
    html = product_page({"price": 27_490_000}, related)

    result = detail(FptShopScraper, html)

    assert (result.price, result.list_price, result.price_type) == (
        27_490_000,
        None,
        PriceType.regular,
    )


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        ("https://schema.org/InStock", StockStatus.in_stock),
        ("InStock", StockStatus.in_stock),
        ("http://schema.org/OutOfStock", StockStatus.out_of_stock),
        ("https://schema.org/OUTOFSTOCK", StockStatus.out_of_stock),
        ("https://schema.org/InStoreOnly", StockStatus.unknown),
        ("https://schema.org/Unheard", StockStatus.unknown),
        ("", StockStatus.unknown),
        (["InStock"], StockStatus.unknown),
        (None, StockStatus.unknown),
    ],
)
def test_schema_stock_handles_whitespace_prefix_and_unknown_values(
    availability: Any, expected: StockStatus
) -> None:
    assert schema_stock({"availability": availability}) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("27490000.00", 27_490_000),
        ("27.490.000", 27_490_000),
        ("27,490,000", 27_490_000),
        (" 27490000 ", 27_490_000),
        ("27490000VND", 27_490_000),
        ("-27490000", None),
        ("27490000 - 30000000", None),
        (27_490_000.0, 27_490_000),
        (27_490_000.5, None),
        (10**400, None),
        (float("nan"), None),
        (float("inf"), None),
    ],
)
def test_schema_price_edge_values(value: object, expected: int | None) -> None:
    assert schema_price(value) == expected
