"""Scraper của An Phát Computer (docs/06 §6, docs/sources/anphat.md).

Trang dựng sẵn ở máy chủ, phân trang bằng `?page=N`. Danh sách không có JSON-LD sản phẩm: mỗi sản
phẩm là `div.p-item`; thẻ không có thông số (nạp bằng JavaScript qua `/ajax/`, robots.txt chặn)
nên `raw_specs` của danh sách để rỗng và pipeline tải trang chi tiết, nơi thông số có nhãn nằm ở
`div.pro-info-summary` và bảng `div#pro-spec`. `parse_*` là hàm thuần; thẻ không đọc được bị bỏ
qua, đếm vào `skipped`.
"""

import logging
import re
import unicodedata
from dataclasses import replace
from typing import Any, ClassVar
from urllib.parse import parse_qs, urljoin, urlsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError
from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.domain.dto import Challenge, ListingItem, ListingPage, ProductDetail
from app.domain.enums import Category, PriceType, SiteKey, StockStatus
from app.normalize.price import parse_price
from app.normalize.url import clean_url
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.http.types import FetchResponse
from app.scrapers.parsing import json_ld_objects, node_text, schema_offer, schema_price

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.anphatpc.com.vn"
# Mọi trang của An Phát (kể cả trang sản phẩm bình thường và trang danh sách rỗng) chứa sẵn form
# đăng ký có ô captcha. Chỉ loại đúng các tên của form đó; dấu hiệu captcha khác (trong thẻ hoặc
# thuộc tính theo luật chung T4.8 ở `challenge.py`) vẫn bị coi là challenge (docs/sources/anphat.md
# mục 7).
_REGISTER_FORM_CAPTCHA = re.compile(
    r"register_captcha|check_user_captcha|captchaimg|/includes/captcha/captcha\.php",
    re.IGNORECASE,
)
# Số sản phẩm mỗi trang (đo ngày 2026-10-19): laptop 24, các nhóm khác 30.
_PAGE_SIZE: dict[Category, int] = {Category.laptop: 24}
_DEFAULT_PAGE_SIZE = 30
# Trang thật có liên kết lạ dạng `/<slug>.html-1`: vẫn là trang sản phẩm của An Phát.
_PRODUCT_PATH = re.compile(r"\.html(?:-\d+)?$")
_STARS = re.compile(r"star-(\d)\b")
_RATING_COUNT = re.compile(r"\((\d{1,10})\)")
_SKU = re.compile(r"^\s*Mã\s*SP\s*:?\s*", re.IGNORECASE)
_HTTP_URL = TypeAdapter(HttpUrl)
_MAX_SPEC_LABEL = 60
MAX_COUNT = 2**31 - 1
_IGNORED_SECTIONS = {"mô tả chi tiết"}  # tiêu đề chung của bảng thông số, không phải một mục


def _clean(text: str) -> str:
    """NFC, bỏ ký tự NUL (PostgreSQL không lưu được), gộp khoảng trắng (kể cả NBSP)."""
    return " ".join(unicodedata.normalize("NFC", text.replace("\x00", "")).split())


def _price(node: LexborNode | None) -> int | None:
    return parse_price(node_text(node)) if node is not None else None


def _image_url(page_url: str, card: LexborNode) -> str | None:
    """Ảnh tải lười ở `data-src` (không có `src`); `src` hỏng chỉ làm mất ảnh, không mất thẻ."""
    for image in card.css("a.p-img img"):
        src = image.attributes.get("data-src") or image.attributes.get("src") or ""
        if src and not src.startswith("data:"):
            try:
                return str(_HTTP_URL.validate_python(urljoin(page_url, src.strip())))
            except (ValueError, ValidationError):
                continue
    return None


def _rating(card: LexborNode) -> tuple[float | None, int | None]:
    """Số sao (`i.icon-star.star-N`) và số lượt "(24)" ngay sau; 0 lượt là chưa có đánh giá."""
    star = card.css_first("i.icon-star")
    if star is None:
        return None, None
    stars = _STARS.search(star.attributes.get("class") or "")
    holder = star.parent
    counted = _RATING_COUNT.search(node_text(holder)) if holder is not None else None
    if stars is None or counted is None:
        return None, None
    votes = int(counted.group(1))
    if votes > MAX_COUNT:  # cột `rating_count` là INTEGER (4 byte)
        return None, None
    value = float(stars.group(1))
    return (value if votes > 0 and value <= 5 else None), votes


def _stock(card: LexborNode) -> StockStatus:
    if card.css_first(".btn-in-stock") is not None:
        return StockStatus.in_stock
    if card.css_first(".btn-out-stock") is not None:  # "Đặt hàng": gọi điện để đặt
        return StockStatus.out_of_stock
    return StockStatus.unknown


def _page_number(page_url: str) -> int:
    values = parse_qs(urlsplit(page_url).query).get("page", ["1"])
    try:
        return max(int(values[0]), 1)
    except ValueError:
        return 1


def _total(tree: LexborHTMLParser) -> int | None:
    """Tổng số sản phẩm của nhóm: "Xem <span class=js-show-total>342</span> kết quả"."""
    node = tree.css_first("span.js-show-total")
    digits = re.sub(r"\D", "", node_text(node))
    return int(digits) if 0 < len(digits) <= 1000 else None  # chuỗi dài bất thường là rác


def _spec(specs: dict[str, str], label: str, value: str) -> None:
    label, value = _clean(label), _clean(value)
    if label and value and len(label) <= _MAX_SPEC_LABEL and label not in specs:
        specs[label] = value


def _summary_specs(tree: LexborHTMLParser, specs: dict[str, str]) -> None:
    """Gạch đầu dòng "Nhãn: giá trị" ở `pro-info-summary`; dòng không có dấu `:` là mô tả tự do."""
    for item in tree.css("div.pro-info-summary span.item"):
        text = _clean(node_text(item)).lstrip("-– ").strip()
        label, sep, value = text.partition(":")
        if sep:
            _spec(specs, label, value)


def _table_specs(tree: LexborHTMLParser, specs: dict[str, str]) -> None:
    """Bảng `#pro-spec`: hàng 2 ô là nhãn | giá trị, hàng 1 ô là tiêu đề mục (nhãn lặp giữa mục)."""
    section = ""
    for row in tree.css("#pro-spec tr"):
        cells = [cell for cell in row.iter() if cell.tag in ("td", "th")]
        texts = [_clean(node_text(cell)) for cell in cells]
        if len(texts) == 1:
            title = texts[0]
            section = "" if title.casefold() in _IGNORED_SECTIONS else title
        elif len(texts) == 2 and texts[0]:
            label = texts[0]
            if section and section != label:
                label = f"{section} / {label}"
            _spec(specs, label, texts[1])


def _product(tree: LexborHTMLParser) -> dict[str, Any] | None:
    for obj in json_ld_objects(tree):
        kind = obj.get("@type")
        if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
            return obj
    return None


def _brand_name(product: dict[str, Any]) -> str | None:
    brand = product.get("brand")
    name = brand.get("name") if isinstance(brand, dict) else brand
    return name.strip() if isinstance(name, str) and name.strip() else None


class AnPhatScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.anphat,
        base_url=_BASE_URL,
        min_delay_s=5.0,
        categories={
            Category.laptop: f"{_BASE_URL}/may-tinh-xach-tay-laptop.html",
            Category.mouse: f"{_BASE_URL}/chuot-may-tinh_dm1291.html",
            Category.keyboard: f"{_BASE_URL}/ban-phim-may-tinh_dm1027.html",
            Category.headset: f"{_BASE_URL}/tai-nghe_dm1180.html",
        },
    )

    def detect_challenge(self, resp: FetchResponse) -> Challenge | None:
        # Fetcher đã coi 5xx có chữ captcha là trang chặn của CDN (không thử lại, trả ngay) và nó
        # xét văn bản gốc, nên ở đây cũng không loại form đăng ký: không để trang lỗi đi tiếp.
        if resp.status >= 500:
            return super().detect_challenge(resp)
        cleaned = replace(resp, text=_REGISTER_FORM_CAPTCHA.sub("", resp.text))
        return super().detect_challenge(cleaned)

    # ---- parse (hàm thuần) ----
    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        tree = LexborHTMLParser(html)
        items: list[ListingItem] = []
        skipped = 0
        cards = tree.css("div.p-item")
        for card in cards:
            try:
                items.append(self._parse_card(card, category, page_url))
            except (ValueError, ValidationError):
                skipped += 1
                logger.warning("Bỏ qua thẻ sản phẩm không đọc được: %s", _card_href(card))
        # Không có `rel="next"` (nút "Xem thêm" nạp bằng JavaScript): suy từ tổng và cỡ trang.
        size = _PAGE_SIZE.get(category, _DEFAULT_PAGE_SIZE)
        total = _total(tree)
        if total is not None:
            has_next = bool(cards) and _page_number(page_url) * size < total
        else:
            has_next = len(cards) >= size
        return ListingPage(items=items, has_next=has_next, next_url=None, skipped=skipped)

    def _parse_card(self, card: LexborNode, category: Category, page_url: str) -> ListingItem:
        href = _card_href(card)
        if not href:
            raise ValueError("card without product link")
        url = clean_url(urljoin(page_url, href))
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc.lower() != urlsplit(_BASE_URL).netloc
            or _PRODUCT_PATH.search(parts.path) is None
        ):
            raise ValueError("card link is not a product page of this site")
        if "_dm" in parts.path.rsplit("/", 1)[-1]:
            raise ValueError("card link is a category page")
        title = _clean(node_text(card.css_first("a.p-name h3")))

        # Chỉ đọc `span.p-price` và `del.p-old-price`: giá ẩn `d-none` (Build PC, combo TP.HCM) dùng
        # lớp khác nên không lẫn vào.
        price = _price(card.css_first(".price-container .p-price"))
        old_price = _price(card.css_first(".price-container .p-old-price"))
        list_price: int | None = None
        if price is not None and old_price is not None:
            if old_price > price:
                list_price = old_price
            else:
                logger.warning("Giá gốc không lớn hơn giá bán, bỏ qua giá gốc: %s", url)
        price_type = PriceType.unknown
        if price is not None:
            price_type = PriceType.sale if list_price is not None else PriceType.regular
        elif card.css_first(".price-container .p-price") is None:
            logger.warning("Thẻ không có giá: %s", url)

        sku = _SKU.sub("", node_text(card.css_first(".p-sku"))).strip()
        rating, rating_count = _rating(card)
        return ListingItem.model_validate(
            {
                "site": SiteKey.anphat,
                "url": url,
                "title": title,
                "price": price,
                "list_price": list_price,
                "price_type": price_type,
                "stock_status": _stock(card),
                "image_url": _image_url(page_url, card),
                "rating": rating,
                "rating_count": rating_count,
                "site_sku": sku or None,
                "category_hint": category,
            }
        )

    def parse_detail(self, html: str, url: str) -> ProductDetail:
        tree = LexborHTMLParser(html)
        specs: dict[str, str] = {}
        _summary_specs(tree, specs)
        _table_specs(tree, specs)
        product = _product(tree) or {}
        return ProductDetail.model_validate(
            {
                "url": clean_url(url),
                # Chỉ lấy giá bán từ JSON-LD. Trang không cho biết giá gốc/loại giá chắc chắn, và
                # `availability` của JSON-LD luôn InStock (khác nút "Đặt hàng" ở thẻ danh sách),
                # nên để `price_type`/`stock_status` là `unknown`: nơi dùng giữ giá trị đã lưu.
                "price": schema_price(schema_offer(product).get("price")),
                "raw_specs": specs,
                # `sku` là "Mã SP" và `mpn` là số nội bộ của An Phát, không phải mã hãng.
                "model_code_hint": None,
                "brand_hint": _brand_name(product),
            }
        )


def _card_href(card: LexborNode) -> str | None:
    link = card.css_first("a.p-name")
    return link.attributes.get("href") if link is not None else None
