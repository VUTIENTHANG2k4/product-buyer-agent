"""AnPhatScraper (app/scrapers/sites/anphat.py) trên fixture đã lưu ở T4.3, không gọi mạng."""

import json
from collections import Counter
from pathlib import Path

import pytest

from app.domain.dto import ListingPage, ProductDetail
from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.robots import parse_robots
from app.scrapers.http.types import FetchResponse
from app.scrapers.registry import SCRAPERS, get_scraper
from app.scrapers.sites.anphat import AnPhatScraper
from tests.fakes import FakeFetcher

BASE = "https://www.anphatpc.com.vn"
# Form đăng ký nằm trong mọi trang của An Phát (kể cả trang sản phẩm bình thường).
REGISTER_FORM = (
    '<form><input type="text" name="register_captcha" onkeyup="check_user_captcha(this.value)"/>'
    '<img src="/includes/captcha/captcha.php?v=" id="captchaimg"/>'
    "<a onclick=\"document.getElementById('captchaimg').src='/includes/captcha/captcha.php?'\">"
    "Đổi ảnh</a></form>"
)


def response(text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=f"{BASE}/x", final_url=f"{BASE}/x", status=status, text=text)


@pytest.fixture
def scraper() -> AnPhatScraper:
    return AnPhatScraper(FakeFetcher({}))


# --- Bộ phát hiện challenge --------------------------------------------------------------------


def test_registration_form_captcha_on_every_page_is_not_a_challenge(
    scraper: AnPhatScraper,
) -> None:
    page = f"<html><body><h1>Chuột Logitech</h1>{REGISTER_FORM}</body></html>"
    assert scraper.detect_challenge(response(page)) is None


def test_empty_listing_page_with_the_registration_form_is_not_a_challenge(
    scraper: AnPhatScraper,
) -> None:
    assert scraper.detect_challenge(response(f"<body>{REGISTER_FORM}</body>")) is None


@pytest.mark.parametrize(
    "markup",
    [
        '<div id="captcha">AB3XZ</div>',
        '<div class="g-recaptcha" data-sitekey="k"></div>',
        '<iframe src="https://newassets.hcaptcha.com/captcha/v1/x"></iframe>',
        "<p>Please verify you are human</p>",
        '<form action="/captcha" method="post"></form>',
        '<img src="/includes/captcha/other.php">',
    ],
)
def test_a_real_captcha_next_to_the_registration_form_is_still_a_challenge(
    scraper: AnPhatScraper, markup: str
) -> None:
    challenge = scraper.detect_challenge(response(f"<body>{REGISTER_FORM}{markup}</body>"))
    assert challenge is not None
    assert challenge.kind is ChallengeKind.captcha
    assert challenge.site is SiteKey.anphat


@pytest.mark.parametrize(
    ("status", "kind"), [(403, ChallengeKind.http_403), (429, ChallengeKind.http_429)]
)
def test_blocking_status_is_a_challenge_even_with_the_registration_form(
    scraper: AnPhatScraper, status: int, kind: ChallengeKind
) -> None:
    challenge = scraper.detect_challenge(response(REGISTER_FORM, status))
    assert challenge is not None and challenge.kind is kind


# --- Cấu hình, đăng ký ------------------------------------------------------------------------

CATEGORY_URLS = {
    Category.laptop: f"{BASE}/may-tinh-xach-tay-laptop.html",
    Category.mouse: f"{BASE}/chuot-may-tinh_dm1291.html",
    Category.keyboard: f"{BASE}/ban-phim-may-tinh_dm1027.html",
    Category.headset: f"{BASE}/tai-nghe_dm1180.html",
}
SLUG = {
    Category.laptop: "laptop",
    Category.mouse: "mouse",
    Category.keyboard: "keyboard",
    Category.headset: "headset",
}
PAGE_SIZE = {Category.laptop: 24, Category.mouse: 30, Category.keyboard: 30, Category.headset: 30}
TOTAL = {Category.laptop: 980, Category.mouse: 342, Category.keyboard: 420, Category.headset: 117}
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "anphat"
MOUSE_PAGE = CATEGORY_URLS[Category.mouse]
LAPTOP_DETAIL = "laptop-hp-victus-15-fa2452tx-d44vlpa"
MOUSE_DETAIL = "chuot-logitech-g102-lightsync"
KEYBOARD_DETAIL = "ban-phim-co-aula-f75-grey-white-milk-white-switch"
HEADSET_DETAIL = "tai-nghe-logitech-g-pro-x3-lightspeed-magenta"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def page_of(scraper: AnPhatScraper, name: str, category: Category, url: str) -> ListingPage:
    return scraper.parse_listing(fixture(f"{name}.html"), category, url)


def first_page(scraper: AnPhatScraper, category: Category) -> ListingPage:
    return page_of(scraper, f"listing_{SLUG[category]}_p1", category, CATEGORY_URLS[category])


def card(
    *,
    href: str | None = "/chuot-thu-x.html",
    title: str = "Chuột thử X",
    price_block: str = '<span class="p-price"> 389.000 đ </span>',
    extra: str = "",
) -> str:
    """Một thẻ sản phẩm tối giản có cùng lớp CSS như trang thật."""
    link = f' href="{href}"' if href is not None else ""
    return (
        f'<div class="p-item" data-id="1"><a{link} class="p-name"><h3>{title}</h3></a>'
        f'<div class="price-container">{price_block}</div>{extra}</div>'
    )


def parse_cards(
    scraper: AnPhatScraper, *cards: str, total: int | None = None, url: str = MOUSE_PAGE
) -> ListingPage:
    count = f'<a>Xem <span class="js-show-total">{total}</span> kết quả</a>' if total else ""
    html = f"<html><body>{count}{''.join(cards)}</body></html>"
    return scraper.parse_listing(html, Category.mouse, url)


def test_config_describes_anphat() -> None:
    config = AnPhatScraper.config
    assert (config.key, config.base_url, config.min_delay_s) == (SiteKey.anphat, BASE, 5.0)
    assert (config.requires_js, config.supports_live_search, config.is_mock) == (
        False,
        False,
        False,
    )
    assert dict(config.categories) == CATEGORY_URLS


def test_scraper_is_registered_and_buildable() -> None:
    assert SCRAPERS[SiteKey.anphat] is AnPhatScraper
    assert isinstance(get_scraper(SiteKey.anphat, FakeFetcher({})), AnPhatScraper)


@pytest.mark.parametrize(("page", "suffix"), [(1, ""), (2, "?page=2"), (12, "?page=12")])
@pytest.mark.parametrize("category", list(CATEGORY_URLS))
def test_listing_url_uses_page_parameter_from_page_two(
    scraper: AnPhatScraper, category: Category, page: int, suffix: str
) -> None:
    assert scraper.listing_url(category, page) == f"{CATEGORY_URLS[category]}{suffix}"


def test_every_url_the_scraper_builds_is_allowed_by_the_saved_robots_txt(
    scraper: AnPhatScraper,
) -> None:
    rules = parse_robots(fixture("robots.txt"), "ProductBuyerAgent/0.1")
    urls = [scraper.listing_url(category, page) for category in CATEGORY_URLS for page in (1, 2, 9)]
    urls += [f"{BASE}/{MOUSE_DETAIL}.html", f"{BASE}/{LAPTOP_DETAIL}.html"]
    assert all(rules.allowed(url) for url in urls)
    assert not rules.allowed(f"{BASE}/ajax/products")  # chứng minh bộ kiểm tra thật sự chặn
    assert not rules.allowed(f"{BASE}/tim-kiem?q=chuot")


def test_live_search_is_not_available(scraper: AnPhatScraper) -> None:
    with pytest.raises(NotImplementedError):
        scraper.search_url("chuot")


# --- Trang danh sách ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", list(CATEGORY_URLS))
def test_first_listing_page_has_a_full_page_of_complete_items(
    scraper: AnPhatScraper, category: Category
) -> None:
    page = first_page(scraper, category)
    assert len(page.items) + page.skipped == PAGE_SIZE[category]
    assert page.has_next is True and page.next_url is None
    item = page.items[0]
    assert item.site is SiteKey.anphat and item.category_hint is category
    assert item.title and item.site_sku and str(item.url).startswith(f"{BASE}/")
    assert item.image_url is not None and str(item.image_url).startswith("https://anphat.com.vn/")
    assert item.raw_specs == {}  # thông số của thẻ nạp bằng JavaScript: để pipeline tải chi tiết


@pytest.mark.parametrize("category", list(CATEGORY_URLS))
def test_listing_items_have_unique_clean_urls_and_positive_integer_prices(
    scraper: AnPhatScraper, category: Category
) -> None:
    items = first_page(scraper, category).items
    urls = [str(item.url) for item in items]
    assert len(set(urls)) == len(urls)
    assert all("?" not in url and "#" not in url for url in urls)
    assert all(item.price is not None and item.price > 0 for item in items)
    assert all(item.list_price is None or item.list_price > (item.price or 0) for item in items)


def test_laptop_page_keeps_the_odd_html_dash_one_link(scraper: AnPhatScraper) -> None:
    page = first_page(scraper, Category.laptop)
    assert page.skipped == 0
    assert any(str(item.url).endswith(".html-1") for item in page.items)


def test_listing_item_counts_by_price_type_match_the_survey(scraper: AnPhatScraper) -> None:
    pages = [first_page(scraper, category) for category in CATEGORY_URLS]
    pages.append(page_of(scraper, "listing_mouse_p12", Category.mouse, f"{MOUSE_PAGE}?page=12"))
    counts = Counter(item.price_type for page in pages for item in page.items)
    assert counts[PriceType.sale] == 105
    assert counts[PriceType.regular] == 21
    assert counts[PriceType.unknown] == 0


def test_discounted_card_reads_old_price_as_list_price(scraper: AnPhatScraper) -> None:
    item = first_page(scraper, Category.mouse).items[0]
    assert item.title == "Chuột Logitech G102 Gen2 LightSync"
    assert (item.price, item.list_price, item.price_type) == (389_000, 449_000, PriceType.sale)
    assert (item.rating, item.rating_count, item.site_sku) == (5.0, 24, "MULG0093")
    assert item.stock_status is StockStatus.in_stock


def test_last_listing_page_has_no_next_and_marks_items_out_of_stock(
    scraper: AnPhatScraper,
) -> None:
    page = page_of(scraper, "listing_mouse_p12", Category.mouse, f"{MOUSE_PAGE}?page=12")
    assert len(page.items) == 12 and page.has_next is False
    assert {item.stock_status for item in page.items} == {StockStatus.out_of_stock}


def test_page_beyond_the_last_is_empty_without_error(scraper: AnPhatScraper) -> None:
    page = page_of(scraper, "listing_mouse_p13", Category.mouse, f"{MOUSE_PAGE}?page=13")
    assert (page.items, page.has_next, page.skipped) == ([], False, 0)


@pytest.mark.parametrize("category", list(CATEGORY_URLS))
def test_has_next_follows_total_and_page_size(scraper: AnPhatScraper, category: Category) -> None:
    size, total = PAGE_SIZE[category], TOTAL[category]
    cards = [card(href=f"/sp-{i}.html") for i in range(size)]
    html = f'<a>Xem <span class="js-show-total">{total}</span> kết quả</a>' + "".join(cards)
    last_page = -(-total // size)
    for number, expected in [(1, True), (last_page - 1, True), (last_page, False)]:
        url = f"{CATEGORY_URLS[category]}?page={number}"
        assert scraper.parse_listing(html, category, url).has_next is expected


def test_has_next_is_false_on_the_last_page_when_the_total_is_an_exact_multiple(
    scraper: AnPhatScraper,
) -> None:
    cards = [card(href=f"/sp-{i}.html") for i in range(30)]
    assert parse_cards(scraper, *cards, total=60, url=f"{MOUSE_PAGE}?page=2").has_next is False
    assert parse_cards(scraper, *cards, total=60, url=MOUSE_PAGE).has_next is True


def test_has_next_falls_back_to_a_full_page_when_the_total_is_missing(
    scraper: AnPhatScraper,
) -> None:
    full = [card(href=f"/sp-{i}.html") for i in range(30)]
    assert parse_cards(scraper, *full).has_next is True
    assert parse_cards(scraper, *full[:29]).has_next is False
    assert parse_cards(scraper).has_next is False


@pytest.mark.parametrize("query", ["page=abc", "page=-3", "page=", "x=1"])
def test_unusable_page_parameter_counts_as_the_first_page(
    scraper: AnPhatScraper, query: str
) -> None:
    page = parse_cards(scraper, card(), total=500, url=f"{MOUSE_PAGE}?{query}")
    assert page.has_next is True


@pytest.mark.parametrize(
    ("price_block", "price", "list_price", "price_type"),
    [
        ('<span class="p-price"> 389.000 đ </span>', 389_000, None, PriceType.regular),
        (
            '<del class="p-old-price"> 449.000 đ </del><span class="p-discount"> -14% </span>'
            '<span class="p-price"> 389.000 đ </span>',
            389_000,
            449_000,
            PriceType.sale,
        ),
        (  # giá gốc bằng giá bán: không phải giảm giá
            '<del class="p-old-price"> 389.000 đ </del><span class="p-price"> 389.000 đ </span>',
            389_000,
            None,
            PriceType.regular,
        ),
        (  # giá gốc thấp hơn giá bán
            '<del class="p-old-price"> 300.000 đ </del><span class="p-price"> 389.000 đ </span>',
            389_000,
            None,
            PriceType.regular,
        ),
        ('<span class="p-price"> Liên hệ </span>', None, None, PriceType.unknown),
        ('<span class="p-price"> 0 đ </span>', None, None, PriceType.unknown),
        ('<span class="p-price"></span>', None, None, PriceType.unknown),
        ("", None, None, PriceType.unknown),
        (  # chỉ có giá gốc: không đoán giá bán
            '<del class="p-old-price"> 449.000 đ </del>',
            None,
            None,
            PriceType.unknown,
        ),
        (  # giá ẩn d-none (Build PC, combo TP.HCM) không được đọc
            '<span class="p-price"> 389.000 đ </span>'
            '<div class="p-price-showroom d-none"><p>Giá Build PC: 100.000 đ</p></div>'
            '<div class="p-price-combo d-none"><p>329.000 đ</p></div>',
            389_000,
            None,
            PriceType.regular,
        ),
    ],
)
def test_price_display_kinds_map_to_price_and_price_type(
    scraper: AnPhatScraper,
    price_block: str,
    price: int | None,
    list_price: int | None,
    price_type: PriceType,
) -> None:
    item = parse_cards(scraper, card(price_block=price_block)).items[0]
    assert (item.price, item.list_price, item.price_type) == (price, list_price, price_type)


def test_promotion_text_and_discount_percentages_are_never_read_as_prices(
    scraper: AnPhatScraper,
) -> None:
    extra = '<div class="p-special-container">Giảm 300.000đ khi mua kèm</div>'
    block = '<span class="p-discount"> -14% </span><span class="p-price"> 389.000 đ </span>'
    item = parse_cards(scraper, card(price_block=block, extra=extra)).items[0]
    assert (item.price, item.list_price) == (389_000, None)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ('<span class="btn-in-stock">Còn hàng</span>', StockStatus.in_stock),
        ('<span class="btn-out-stock">Đặt hàng</span>', StockStatus.out_of_stock),
        ("", StockStatus.unknown),
    ],
)
def test_stock_button_maps_to_stock_status(
    scraper: AnPhatScraper, extra: str, expected: StockStatus
) -> None:
    assert parse_cards(scraper, card(extra=extra)).items[0].stock_status is expected


@pytest.mark.parametrize(
    ("holder", "expected"),
    [
        ('<div><i class="icon-star star-5"></i>(24)</div>', (5.0, 24)),
        ('<div><i class="icon-star star-4"></i> (3) </div>', (4.0, 3)),
        ('<div><i class="icon-star star-0"></i>(0)</div>', (None, 0)),
        ('<div><i class="icon-star star-5"></i>chưa có</div>', (None, None)),
        ('<div><i class="icon-star"></i>(2)</div>', (None, None)),
        ("", (None, None)),
    ],
)
def test_rating_comes_from_the_star_class_and_the_vote_count(
    scraper: AnPhatScraper, holder: str, expected: tuple[float | None, int | None]
) -> None:
    item = parse_cards(scraper, card(extra=holder)).items[0]
    assert (item.rating, item.rating_count) == expected


@pytest.mark.parametrize(
    ("sku_html", "expected"),
    [
        ('<span class="p-sku">Mã SP: MULG0093 </span>', "MULG0093"),
        ('<span class="p-sku">Mã SP:SEVERIBM33</span>', "SEVERIBM33"),
        ('<span class="p-sku">Mã SP: </span>', None),
        ("", None),
    ],
)
def test_site_sku_is_the_ma_sp_text(
    scraper: AnPhatScraper, sku_html: str, expected: str | None
) -> None:
    assert parse_cards(scraper, card(extra=sku_html)).items[0].site_sku == expected


@pytest.mark.parametrize(
    ("img", "expected"),
    [
        (
            '<a class="p-img"><img data-src="https://anphat.com.vn/a.jpg"></a>',
            "https://anphat.com.vn/a.jpg",
        ),
        ('<a class="p-img"><img data-src="/media/a.jpg"></a>', f"{BASE}/media/a.jpg"),
        ('<a class="p-img"><img src="https://x.example/b.jpg"></a>', "https://x.example/b.jpg"),
        ('<a class="p-img"><img src="data:image/png;base64,AAA"></a>', None),
        ('<a class="p-img"><img data-src="javascript:alert(1)"></a>', None),
        ('<a class="p-img"></a>', None),
    ],
)
def test_image_url_is_absolute_http_or_none(
    scraper: AnPhatScraper, img: str, expected: str | None
) -> None:
    item = parse_cards(scraper, card(extra=img)).items[0]
    assert (str(item.image_url) if item.image_url else None) == expected


def test_relative_links_tracking_parameters_and_odd_suffix_are_handled(
    scraper: AnPhatScraper,
) -> None:
    page = parse_cards(
        scraper,
        card(href="/chuot-a.html?utm_source=x"),
        card(href="/chuot-b_id123.html"),
        card(href="/laptop-c.html-1"),
        card(href=f"{BASE}/chuot-d.html#top"),
    )
    assert [str(item.url) for item in page.items] == [
        f"{BASE}/chuot-a.html",
        f"{BASE}/chuot-b_id123.html",
        f"{BASE}/laptop-c.html-1",
        f"{BASE}/chuot-d.html",
    ]


@pytest.mark.parametrize(
    "href",
    [
        None,
        "",
        "#",
        "javascript:void(0)",
        "/chuot-may-tinh_dm1291.html",  # trang danh mục
        "/tin-tuc/bai-viet",  # không phải .html
        "https://other.example/chuot-a.html",
    ],
)
def test_card_that_is_not_a_product_page_of_this_site_is_skipped_and_counted(
    scraper: AnPhatScraper, href: str | None
) -> None:
    page = parse_cards(scraper, card(href=href), card(href="/chuot-ok.html"))
    assert (len(page.items), page.skipped) == (1, 1)


def test_card_without_a_title_is_skipped(scraper: AnPhatScraper) -> None:
    page = parse_cards(scraper, card(title="   "), card())
    assert (len(page.items), page.skipped) == (1, 1)


def test_title_is_normalised(scraper: AnPhatScraper) -> None:
    item = parse_cards(scraper, card(title="  Chuột\xa0 Logitech \n G102\x00 ")).items[0]
    assert item.title == "Chuột Logitech G102"


# --- Trang chi tiết ----------------------------------------------------------------------------


def detail(scraper: AnPhatScraper, slug: str) -> ProductDetail:
    return scraper.parse_detail(fixture(f"detail_{slug}.html"), f"{BASE}/{slug}.html")


def test_laptop_detail_reads_labelled_specs_from_summary_and_table(
    scraper: AnPhatScraper,
) -> None:
    result = detail(scraper, LAPTOP_DETAIL)
    assert result.brand_hint == "HP" and result.model_code_hint is None
    assert str(result.url) == f"{BASE}/{LAPTOP_DETAIL}.html"
    specs = result.raw_specs
    assert specs["CPU"].startswith("Intel Core i5-13420H")
    assert specs["RAM"].startswith("16GB DDR4")
    assert "RTX 3050" in specs["VGA"]
    assert specs["Hãng sản xuất"] == "Laptop HP"
    assert any(label.startswith("Ổ cứng / ") for label in specs)  # nhãn lặp được thêm tên mục
    assert all(value and len(label) <= 60 for label, value in specs.items())


def test_mouse_detail_reads_the_spec_table_and_ignores_the_generic_section_title(
    scraper: AnPhatScraper,
) -> None:
    result = detail(scraper, MOUSE_DETAIL)
    assert result.brand_hint == "Logitech"
    assert result.raw_specs["Chuẩn giao tiếp"] == "USB"
    assert result.raw_specs["Độ phân giải"] == "8000DPI"
    assert not any(label.startswith("Mô tả chi tiết") for label in result.raw_specs)


def test_keyboard_detail_has_only_summary_bullets_as_specs(scraper: AnPhatScraper) -> None:
    result = detail(scraper, KEYBOARD_DETAIL)
    assert result.brand_hint == "Aula"
    assert result.raw_specs["Kết nối"] == "3 mode có dây Type-C & không dây 2.4G & BT"
    assert result.raw_specs["Loại switch"] == "Milk White switch"


def test_headset_detail_reads_what_little_is_labelled(scraper: AnPhatScraper) -> None:
    result = detail(scraper, HEADSET_DETAIL)
    assert result.brand_hint == "Logitech"
    assert "Hỗ trợ 3 kết nối" in result.raw_specs


def test_detail_never_exposes_reviewer_names(scraper: AnPhatScraper) -> None:
    for slug in (LAPTOP_DETAIL, MOUSE_DETAIL, KEYBOARD_DETAIL, HEADSET_DETAIL):
        assert "[đã ẩn]" not in str(detail(scraper, slug).model_dump())


def test_summary_and_table_edge_cases(scraper: AnPhatScraper) -> None:
    html = (
        '<div class="pro-info-summary">'
        '<span class="item">- Kết nối: Bluetooth</span>'
        '<span class="item">Chỉ là mô tả tự do không có nhãn</span>'
        '<span class="item">: không có nhãn</span>'
        '<span class="item">Nhãn rỗng:   </span>'
        f'<span class="item">{"N" * 61}: quá dài</span>'
        '<span class="item">Kết nối: bị trùng nhãn</span>'
        "</div>"
        '<div id="pro-spec"><table>'
        "<tr><td>Mô tả chi tiết</td></tr>"
        "<tr><td>Hãng</td><td> Logitech\xa0</td></tr>"
        "<tr><td>Bộ nhớ</td></tr>"
        "<tr><td>Dung lượng</td><td>16 GB</td></tr>"
        "<tr><td>Bộ nhớ</td><td>DDR5</td></tr>"
        "<tr><td></td><td>không nhãn</td></tr>"
        "<tr><td>Màu</td><td>  </td></tr>"
        "<tr><td>a</td><td>b</td><td>c</td></tr>"
        "</table></div>"
    )
    result = scraper.parse_detail(html, f"{BASE}/x.html")
    assert result.raw_specs == {
        "Kết nối": "Bluetooth",
        "Hãng": "Logitech",
        "Bộ nhớ / Dung lượng": "16 GB",
        "Bộ nhớ": "DDR5",
    }


def test_detail_without_json_ld_or_specs_is_empty_not_an_error(scraper: AnPhatScraper) -> None:
    result = scraper.parse_detail("<html><body>trống</body></html>", f"{BASE}/x.html?utm_source=a")
    assert (result.raw_specs, result.brand_hint, result.model_code_hint) == ({}, None, None)
    assert str(result.url) == f"{BASE}/x.html"


@pytest.mark.parametrize(
    ("brand", "expected"),
    [
        ({"@type": "Brand", "name": " Acer "}, "Acer"),
        ("Acer", "Acer"),
        ({"name": ""}, None),
        ({}, None),
        (5, None),
        (None, None),
    ],
)
def test_brand_hint_handles_json_ld_variants(
    scraper: AnPhatScraper, brand: object, expected: str | None
) -> None:
    ld = json.dumps({"@type": "Product", "brand": brand})
    html = f'<script type="application/ld+json">{ld}</script>'
    assert scraper.parse_detail(html, f"{BASE}/x.html").brand_hint == expected


def test_product_type_may_be_a_list_in_json_ld(scraper: AnPhatScraper) -> None:
    ld = json.dumps({"@type": ["Thing", "Product"], "brand": "Acer"})
    html = f'<script type="application/ld+json">{ld}</script>'
    assert scraper.parse_detail(html, f"{BASE}/x.html").brand_hint == "Acer"


# --- Điều phối ---------------------------------------------------------------------------------


def served(url: str, text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=status, text=text)


async def test_crawl_category_requests_page_urls_in_order_and_stops_at_max_pages() -> None:
    page2 = f"{MOUSE_PAGE}?page=2"
    fetcher = FakeFetcher(
        {
            MOUSE_PAGE: served(MOUSE_PAGE, fixture("listing_mouse_p1.html")),
            page2: served(page2, fixture("listing_mouse_p1.html")),
        }
    )
    pages = [p async for p in AnPhatScraper(fetcher).crawl_category(Category.mouse, max_pages=2)]
    assert [len(p.items) for p in pages] == [30, 30]
    assert fetcher.requested == [MOUSE_PAGE, page2]


async def test_crawl_category_stops_when_has_next_is_false() -> None:
    last = f"{MOUSE_PAGE}?page=12"
    fetcher = FakeFetcher({last: served(last, fixture("listing_mouse_p12.html"))})
    scraper = AnPhatScraper(fetcher)
    pages = [p async for p in scraper.crawl_category(Category.mouse, 12, start_page=12)]
    assert len(pages) == 1 and pages[0].has_next is False
    assert fetcher.requested == [last]


async def test_crawl_category_blocks_on_a_real_captcha_but_not_on_the_register_form() -> None:
    plain = FakeFetcher({MOUSE_PAGE: served(MOUSE_PAGE, "<div id='captcha'>AB3XZ</div>")})
    with pytest.raises(ChallengeDetected):
        _ = [p async for p in AnPhatScraper(plain).crawl_category(Category.mouse, 1)]
    ok = FakeFetcher({MOUSE_PAGE: served(MOUSE_PAGE, fixture("listing_mouse_p1.html"))})
    pages = [p async for p in AnPhatScraper(ok).crawl_category(Category.mouse, 1)]
    assert len(pages[0].items) == 30


async def test_fetch_detail_goes_through_the_fetcher_and_rejects_foreign_hosts() -> None:
    url = f"{BASE}/{MOUSE_DETAIL}.html"
    fetcher = FakeFetcher({url: served(url, fixture(f"detail_{MOUSE_DETAIL}.html"))})
    scraper = AnPhatScraper(fetcher)
    result = await scraper.fetch_detail(url)
    assert result.brand_hint == "Logitech" and fetcher.requested == [url]
    with pytest.raises(ValueError, match="outside"):
        await scraper.fetch_detail("https://anphat.com.vn/x.html")


@pytest.mark.parametrize("name", sorted(path.name for path in FIXTURE_DIR.glob("*.html")))
def test_real_pages_are_not_flagged_as_challenges(scraper: AnPhatScraper, name: str) -> None:
    assert scraper.detect_challenge(served(f"{BASE}/x", fixture(name))) is None
