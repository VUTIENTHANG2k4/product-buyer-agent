"""Scraper của GearVN (docs/06 §6, docs/sources/gearvn.md).

Trang dựng sẵn ở máy chủ nên không cần JavaScript. Danh sách không có JSON-LD sản phẩm: mỗi sản
phẩm là thẻ `a.product-card`, đọc theo thuộc tính `data-slot` (lớp Tailwind dài và dễ đổi). Chi tiết
dùng JSON-LD `Product`. `parse_*` là hàm thuần; thẻ không đọc được bị bỏ qua, đếm vào `skipped`.
"""

import logging
import re
from typing import Any, ClassVar
from urllib.parse import urlencode, urljoin

from pydantic import ValidationError
from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.domain.dto import ListingItem, ListingPage, ProductDetail
from app.domain.enums import Category, PriceType, SiteKey
from app.normalize.price import parse_price
from app.normalize.url import clean_url
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.parsing import json_ld_objects, node_text

logger = logging.getLogger(__name__)

_BASE_URL = "https://gearvn.com"
# Giá hiển thị đúng dạng "24.990.000đ" (chữ đ thường): khuyến mãi như "300.000Đ" không khớp.
_PRICE_TEXT = re.compile(r"^\d{1,3}(?:\.\d{3})+đ$")


def _prices(card: LexborNode) -> list[int]:
    """Các giá đọc được trên thẻ theo thứ tự xuất hiện (giá gốc trước, giá bán sau)."""
    prices: list[int] = []
    for span in card.css("span"):
        if len(span.css("span")) > 1:  # `css` gồm cả chính nó: bỏ span bọc ngoài, tránh đếm trùng
            continue
        text = node_text(span)
        if _PRICE_TEXT.match(text):
            price = parse_price(text)
            if price is not None:
                prices.append(price)
    return prices


def _image_src(card: LexborNode) -> str | None:
    for image in card.css("img"):
        if image.attributes.get("data-slot") == "product-flag-graphic":
            continue
        src = image.attributes.get("src") or ""
        if src and not src.startswith("data:"):
            return src
    return None


def _is_product(obj: dict[str, Any]) -> bool:
    kind = obj.get("@type")
    return kind == "Product" or (isinstance(kind, list) and "Product" in kind)


def _brand_name(product: dict[str, Any]) -> str | None:
    brand = product.get("brand")
    name = brand.get("name") if isinstance(brand, dict) else brand
    return name.strip() if isinstance(name, str) and name.strip() else None


def _additional_properties(product: dict[str, Any]) -> dict[str, str]:
    """`additionalProperty[{name, value}]` → `nhãn → giá trị`; nhãn lặp thì nối giá trị mới."""
    specs: dict[str, str] = {}
    properties = product.get("additionalProperty")
    for prop in properties if isinstance(properties, list) else []:
        if not isinstance(prop, dict):
            continue
        name, value = prop.get("name"), prop.get("value")
        if not isinstance(name, str) or not isinstance(value, str | int | float):
            continue
        label, text = name.strip(), str(value).strip()
        if not label or not text:
            continue
        values = specs[label].split("; ") if label in specs else []
        if text not in values:
            specs[label] = "; ".join([*values, text])
    return specs


class GearVNScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.gearvn,
        base_url=_BASE_URL,
        min_delay_s=5.0,
        supports_live_search=True,
        categories={
            Category.laptop: f"{_BASE_URL}/collections/laptop",
            Category.mouse: f"{_BASE_URL}/collections/chuot-may-tinh",
            Category.keyboard: f"{_BASE_URL}/collections/ban-phim-may-tinh",
            Category.headset: f"{_BASE_URL}/collections/tai-nghe-may-tinh",
        },
    )

    def search_url(self, query: str) -> str:
        return f"{_BASE_URL}/search?{urlencode({'q': query})}"

    # ---- parse (hàm thuần) ----
    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        tree = LexborHTMLParser(html)
        items: list[ListingItem] = []
        skipped = 0
        for card in tree.css("a.product-card"):
            try:
                items.append(self._parse_card(card, category, page_url))
            except (ValueError, ValidationError):
                skipped += 1
                logger.warning(
                    "Bỏ qua thẻ sản phẩm không đọc được: %s", card.attributes.get("href")
                )
        next_link = tree.css_first("link[rel=next]")
        href = next_link.attributes.get("href") if next_link is not None else None
        next_url = clean_url(urljoin(page_url, href)) if href else None
        return ListingPage.model_validate(
            {
                "items": items,
                "has_next": next_url is not None,
                "next_url": next_url,
                "skipped": skipped,
            }
        )

    def _parse_card(self, card: LexborNode, category: Category, page_url: str) -> ListingItem:
        href = card.attributes.get("href")
        if not href:
            raise ValueError("card without product link")
        url = clean_url(urljoin(page_url, href))
        content = card.css_first("[data-slot=product-card-content]")
        title = node_text(content.css_first("p")) if content is not None else ""
        image_src = _image_src(card)

        # Khuyến mãi ("Mua kèm giá ưu đãi…", quà tặng) không phải giá: bỏ trước khi đọc giá.
        for promotion in card.css("[data-slot=product-promotion]"):
            promotion.decompose()
        prices = _prices(card)
        price: int | None = None
        list_price: int | None = None
        if card.css_first("[data-slot=product-discontinued-price]") is None and prices:
            price = prices[-1]
            if len(prices) > 1 and prices[0] > price:
                list_price = prices[0]
        price_type = PriceType.unknown
        if price is not None:
            price_type = PriceType.sale if list_price is not None else PriceType.regular

        return ListingItem.model_validate(
            {
                "site": SiteKey.gearvn,
                "url": url,
                "title": title,
                "price": price,
                "list_price": list_price,
                "price_type": price_type,
                "image_url": urljoin(page_url, image_src) if image_src else None,
                "category_hint": category,
            }
        )

    def parse_detail(self, html: str, url: str) -> ProductDetail:
        tree = LexborHTMLParser(html)
        product = next((obj for obj in json_ld_objects(tree) if _is_product(obj)), {})
        mpn = product.get("mpn")
        return ProductDetail.model_validate(
            {
                "url": clean_url(url),
                "raw_specs": _additional_properties(product),
                # `sku` của GearVN là mã nội bộ, không phải mã hãng: chỉ lấy `mpn` nếu trang có.
                "model_code_hint": mpn.strip() if isinstance(mpn, str) and mpn.strip() else None,
                "brand_hint": _brand_name(product),
            }
        )
