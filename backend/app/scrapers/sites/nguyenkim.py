"""Scraper của Nguyễn Kim, chỉ nhóm điện thoại (docs/06 §6, docs/sources/nguyenkim.md, ADR-0011).

Trang là Next.js dựng sẵn ở máy chủ: danh mục `/dien-thoai.c?page=N` nhúng 25 sản phẩm (có giá)
trong `<script id="__NEXT_DATA__">`; trang chi tiết nhúng thuộc tính sản phẩm và JSON-LD `Product`.
Đây là dữ liệu có sẵn trong HTML, không gọi API nội bộ. Trang **tìm kiếm** thì rỗng nếu không chạy
JavaScript (ADR-0010) nên không dùng cho tầng 2. `parse_*` là hàm thuần; mục không đọc được bị bỏ
qua, đếm vào `skipped`.
"""

import json
import logging
import re
import unicodedata
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from pydantic import HttpUrl, TypeAdapter, ValidationError
from selectolax.lexbor import LexborHTMLParser

from app.domain.dto import ListingItem, ListingPage, ProductDetail
from app.domain.enums import Category, PriceType, SiteKey
from app.normalize.url import clean_url
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.parsing import json_ld_objects, schema_offer, schema_price, schema_stock

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.nguyenkim.com"
_HTTP_URL = TypeAdapter(HttpUrl)
# Đường dẫn sản phẩm là `/<slug><postfix>`: một đoạn, bắt đầu bằng chữ/số (không phải `.`/`..`),
# không có `/`, `?`, `#`.
_PATH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_SPEC_VALUE = 500  # giá trị thuộc tính dài hơn là rác (hoặc đoạn quảng cáo): bỏ


def _text(value: object) -> str:
    """Chuỗi đã bỏ NUL (PostgreSQL không lưu được) và khoảng trắng thừa; không phải chuỗi → rỗng."""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFC", " ".join(value.replace("\x00", "").split()))


def _vi(value: object) -> str:
    """Văn bản tiếng Việt của trường đa ngôn ngữ `{"vi": "...", "en": "..."}`."""
    return _text(value.get("vi")) if isinstance(value, dict) else ""


def _page_props(html: str) -> dict[str, Any]:
    """`props.pageProps` trong `__NEXT_DATA__`; rỗng nếu trang không có hoặc JSON hỏng."""
    node = LexborHTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        return {}
    try:
        data = json.loads(node.text())
    except (ValueError, RecursionError):
        logger.warning("__NEXT_DATA__ không hợp lệ, bỏ qua")
        return {}
    props = data.get("props") if isinstance(data, dict) else None
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    return page_props if isinstance(page_props, dict) else {}


def _prices(entry: dict[str, Any]) -> dict[str, Any]:
    """Giá bán (`salePrice`, rồi `mediaPrice`, rồi `price`), giá niêm yết và loại giá.

    `price` là giá niêm yết; chỉ tính là giá gốc khi lớn hơn giá bán. `finalPrice` (đã trừ mã giảm
    theo điều kiện) không lưu.
    """
    listed = schema_price(entry.get("price"))
    selling = (
        schema_price(entry.get("salePrice")) or schema_price(entry.get("mediaPrice")) or listed
    )
    list_price = listed if listed is not None and selling is not None and listed > selling else None
    price_type = PriceType.unknown
    if selling is not None:
        price_type = PriceType.sale if list_price is not None else PriceType.regular
    return {"price": selling, "list_price": list_price, "price_type": price_type}


def _product_url(entry: dict[str, Any]) -> str:
    slugs = entry.get("slugs")
    if not isinstance(slugs, dict):
        raise ValueError("product without slugs")
    slug, postfix = _vi(slugs.get("value")), _text(slugs.get("postfix"))
    path = f"{slug}{postfix}"
    if not slug or not _PATH_PART.match(path):
        raise ValueError("product with an unusable slug")
    return clean_url(f"{_BASE_URL}/{path}")


def _image_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or value.startswith("data:"):
        return None
    try:
        return str(_HTTP_URL.validate_python(value.strip()))
    except (ValueError, ValidationError):
        return None


def _property_value(prop: dict[str, Any]) -> str:
    """Giá trị của một thuộc tính: ô nhập (`value`) hoặc các lựa chọn (`values[]`) nối bằng "; "."""
    own = _vi(prop.get("value"))
    if own:
        return own
    values = prop.get("values")
    chosen = (
        [_vi(item.get("value")) for item in values if isinstance(item, dict)]
        if isinstance(values, list)
        else []
    )
    return "; ".join(dict.fromkeys(text for text in chosen if text))


def _properties(data: dict[str, Any]) -> dict[str, str]:
    """`properties[]` của trang chi tiết → `nhãn → giá trị`; bỏ giá trị rỗng/quá dài."""
    specs: dict[str, str] = {}
    properties = data.get("properties")
    for prop in properties if isinstance(properties, list) else []:
        if not isinstance(prop, dict):
            continue
        label, value = _vi(prop.get("name")), _property_value(prop)
        if not label or not value or len(value) > _MAX_SPEC_VALUE:
            continue
        values = specs[label].split("; ") if label in specs else []
        if value not in values:
            specs[label] = "; ".join([*values, value])
    return specs


def _json_ld_product(tree: LexborHTMLParser) -> dict[str, Any]:
    for obj in json_ld_objects(tree):
        kind = obj.get("@type")
        if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
            return obj
    return {}


def _brand(data: dict[str, Any], product: dict[str, Any]) -> str | None:
    brand = product.get("brand")
    name = _text(brand.get("name") if isinstance(brand, dict) else brand)
    return name or _vi(data.get("brandName")) or None


class NguyenKimScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.nguyenkim,
        base_url=_BASE_URL,
        min_delay_s=5.0,
        requires_js=False,  # danh mục và chi tiết dựng sẵn; chỉ tìm kiếm cần JS (ADR-0010)
        supports_live_search=False,
        categories={Category.phone: f"{_BASE_URL}/dien-thoai.c"},
    )

    # ---- parse (hàm thuần) ----
    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        """Một trang danh mục (25 sản phẩm). Không có `__NEXT_DATA__`/danh sách → trang rỗng."""
        detail = _page_props(html).get("pageDetail")
        entries = detail.get("data") if isinstance(detail, dict) else None
        if not isinstance(detail, dict) or not isinstance(entries, list):
            return ListingPage(items=[], has_next=False)
        items: list[ListingItem] = []
        skipped = 0
        for entry in entries:
            try:
                items.append(self._parse_entry(entry, category))
            except (ValueError, ValidationError):
                skipped += 1
                logger.warning("Bỏ qua sản phẩm không đọc được: %r", _vi(_name_of(entry)))
        page, pages = detail.get("page"), detail.get("pages")
        has_next = (
            isinstance(page, int)
            and isinstance(pages, int)
            and not isinstance(page, bool)
            and not isinstance(pages, bool)
            and page < pages
            and bool(entries)
        )
        # URL trang sau do `BaseScraper.crawl_category` dựng bằng `listing_url` (`?page=N`).
        return ListingPage(items=items, has_next=has_next, skipped=skipped)

    async def crawl_category(
        self,
        category: Category,
        max_pages: int,
        *,
        start_page: int = 1,
        expect_items: bool = False,
    ) -> AsyncIterator[ListingPage]:
        """Như `BaseScraper.crawl_category`, và dừng khi một trang trả lại đúng các sản phẩm của
        trang trước (máy chủ bỏ qua `?page=N`): không đếm lặp cùng một danh sách nhiều lần."""
        previous: frozenset[str] | None = None
        async for page in super().crawl_category(
            category, max_pages, start_page=start_page, expect_items=expect_items
        ):
            urls = frozenset(str(item.url) for item in page.items)
            if urls and urls == previous:
                logger.warning("Trang danh mục trùng trang trước, dừng phân trang")
                yield ListingPage(items=[], has_next=False, pagination_loop=True)
                return
            previous = urls
            yield page

    def _parse_entry(self, entry: object, category: Category) -> ListingItem:
        if not isinstance(entry, dict):
            raise ValueError("product entry is not an object")
        code = _text(entry.get("code"))
        return ListingItem.model_validate(
            {
                "site": SiteKey.nguyenkim,
                "url": _product_url(entry),
                "title": _vi(entry.get("name")),
                **_prices(entry),
                "stock_status": schema_stock({"availability": _text(entry.get("stockStatus"))}),
                "image_url": _image_url(entry.get("thumbnail")),
                "site_sku": code or None,
                "category_hint": category,
            }
        )

    def parse_detail(self, html: str, url: str) -> ProductDetail:
        """Chi tiết một máy: giá từ `__NEXT_DATA__` (JSON-LD dự phòng), thuộc tính có nhãn."""
        tree = LexborHTMLParser(html)
        detail = _page_props(html).get("pageDetail")
        data = detail.get("data") if isinstance(detail, dict) else None
        data = data if isinstance(data, dict) else {}
        product = _json_ld_product(tree)
        prices = _prices(data)
        if prices["price"] is None:  # không có trong __NEXT_DATA__: dùng giá công khai của JSON-LD
            offer = schema_offer(product)
            prices = _prices({"price": offer.get("price")})
        stock = _text(data.get("stockStatus")) or str(schema_offer(product).get("availability"))
        mpn = product.get("mpn")
        return ProductDetail.model_validate(
            {
                "url": clean_url(url),
                **prices,
                "stock_status": schema_stock({"availability": stock}),
                "raw_specs": _properties(data),
                # `mpn` là mã hãng kèm cấu hình/màu ("CPH2859-8/256/TRANG"); điện thoại không dùng
                # mã model để ghép (chỉ laptop), nên chỉ giữ làm gợi ý.
                "model_code_hint": _text(mpn) or None,
                "brand_hint": _brand(data, product),
            }
        )


def _name_of(entry: object) -> object:
    return entry.get("name") if isinstance(entry, dict) else None
