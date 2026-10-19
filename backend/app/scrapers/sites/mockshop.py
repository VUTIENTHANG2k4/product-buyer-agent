"""Scraper của mock-shop (docs/06 §5): dữ liệu hư cấu cho test và demo.

Thứ tự ưu tiên của docs/06 §6: JSON-LD (giá, tồn kho, mã, ảnh) rồi thẻ HTML (giá gốc, thông số
rút gọn, tên). `parse_*` là hàm thuần; thẻ không đọc được bị bỏ qua, đếm vào `skipped`.
"""

import logging
from typing import Any, ClassVar
from urllib.parse import urlencode, urljoin

from pydantic import ValidationError
from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.config import get_settings
from app.domain.dto import Challenge, ListingItem, ListingPage, ProductDetail
from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus
from app.normalize.price import parse_price
from app.normalize.url import clean_url
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.http.types import FetchResponse
from app.scrapers.parsing import json_ld_objects, node_text

logger = logging.getLogger(__name__)

_BASE_URL = get_settings().mock_shop_url.rstrip("/")


def _ld_products_by_url(page_url: str, objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Product trong `ItemList` (và Product đứng riêng), khóa theo URL đã làm sạch."""
    products: dict[str, dict[str, Any]] = {}
    for obj in objects:
        candidates: list[Any] = [obj]
        if obj.get("@type") == "ItemList":
            candidates = [
                element.get("item")
                for element in obj.get("itemListElement", [])
                if isinstance(element, dict)
            ]
        for candidate in candidates:
            if isinstance(candidate, dict) and isinstance(candidate.get("url"), str):
                try:
                    products[clean_url(urljoin(page_url, candidate["url"]))] = candidate
                except ValueError:
                    continue
    return products


def _ld_price(product: dict[str, Any]) -> int | None:
    offers = product.get("offers")
    price = offers.get("price") if isinstance(offers, dict) else None
    return price if isinstance(price, int) and not isinstance(price, bool) else None


def _stock(ld_product: dict[str, Any] | None, card: LexborNode) -> StockStatus:
    offers = ld_product.get("offers") if ld_product else None
    availability = offers.get("availability") if isinstance(offers, dict) else None
    if isinstance(availability, str):
        if availability.endswith("InStock"):
            return StockStatus.in_stock
        if availability.endswith("OutOfStock"):
            return StockStatus.out_of_stock
    stock = card.css_first(".stock")
    classes = (stock.attributes.get("class") or "") if stock is not None else ""
    if "out-of-stock" in classes:
        return StockStatus.out_of_stock
    if "in-stock" in classes:
        return StockStatus.in_stock
    return StockStatus.unknown


def _mini_specs(card: LexborNode) -> dict[str, str]:
    specs: dict[str, str] = {}
    for item in card.css("ul.mini-specs li"):
        label, sep, value = item.text(strip=True).partition(":")
        if sep and label.strip() and value.strip():
            specs[label.strip()] = value.strip()
    return specs


def _int_attr(node: LexborNode | None, name: str) -> int | None:
    raw = node.attributes.get(name) if node is not None else None
    return int(raw) if raw is not None and raw.isdigit() else None


def _float_attr(node: LexborNode | None, name: str) -> float | None:
    raw = node.attributes.get(name) if node is not None else None
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


class MockShopScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.mockshop,
        base_url=_BASE_URL,
        min_delay_s=0.0,  # độ trễ mock-shop do MOCK_SHOP_DELAY_SECONDS quyết định (docs/06 §3)
        supports_live_search=True,
        categories={
            category: f"{_BASE_URL}/c/{category.value}"
            for category in (Category.laptop, Category.mouse, Category.keyboard, Category.headset)
        },
        is_mock=True,
    )

    def search_url(self, query: str) -> str:
        return f"{_BASE_URL}/search?{urlencode({'q': query})}"

    # ---- parse (hàm thuần) ----
    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        tree = LexborHTMLParser(html)
        ld_products = _ld_products_by_url(page_url, json_ld_objects(tree))
        items: list[ListingItem] = []
        skipped = 0
        for card in tree.css("li.product-card"):
            try:
                items.append(self._parse_card(card, category, page_url, ld_products))
            except (ValueError, ValidationError, KeyError):
                skipped += 1
                logger.warning(
                    "Bỏ qua thẻ sản phẩm không đọc được: %s", card.attributes.get("data-slug")
                )
        next_link = tree.css_first("a[rel=next]")
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

    def _parse_card(
        self,
        card: LexborNode,
        category: Category,
        page_url: str,
        ld_products: dict[str, dict[str, Any]],
    ) -> ListingItem:
        link = card.css_first("a.product-link")
        href = link.attributes.get("href") if link is not None else None
        if not href:
            raise ValueError("card without product link")
        url = clean_url(urljoin(page_url, href))
        ld_product = ld_products.get(url)

        price = _ld_price(ld_product) if ld_product else None
        if price is None:
            price = parse_price(node_text(card.css_first(".price")))
        list_price = parse_price(node_text(card.css_first(".old-price")))
        if list_price is not None and (price is None or list_price <= price):
            list_price = None
        price_type = PriceType.unknown
        if price is not None:
            price_type = PriceType.sale if list_price is not None else PriceType.regular

        image = card.css_first("img")
        image_src = image.attributes.get("src") if image is not None else None
        rating_node = card.css_first(".rating")
        return ListingItem.model_validate(
            {
                "site": SiteKey.mockshop,
                "url": url,
                "title": node_text(card.css_first(".product-name")),
                "price": price,
                "list_price": list_price,
                "price_type": price_type,
                "stock_status": _stock(ld_product, card),
                "image_url": urljoin(page_url, image_src) if image_src else None,
                "rating": _float_attr(rating_node, "data-rating"),
                "rating_count": _int_attr(rating_node, "data-count"),
                "site_sku": card.attributes.get("data-sku"),
                "raw_specs": _mini_specs(card),
                "category_hint": category,
            }
        )

    def parse_detail(self, html: str, url: str) -> ProductDetail:
        tree = LexborHTMLParser(html)
        raw_specs: dict[str, str] = {}
        for row in tree.css("table.specs tr"):
            label, value = node_text(row.css_first("th")), node_text(row.css_first("td"))
            if label and value:
                raw_specs[label] = value
        product = next((o for o in json_ld_objects(tree) if o.get("@type") == "Product"), {})
        brand = product.get("brand")
        mpn = product.get("mpn") or product.get("sku")
        return ProductDetail.model_validate(
            {
                "url": clean_url(url),
                "raw_specs": raw_specs,
                "model_code_hint": mpn if isinstance(mpn, str) and mpn else None,
                "brand_hint": brand.get("name") if isinstance(brand, dict) else None,
            }
        )

    # ---- challenge ----
    def challenge_submission(self, challenge: Challenge, answer: str) -> tuple[str, dict[str, str]]:
        """Form `POST /captcha`: `token` của trang thử thách và `answer` do người nhập."""
        return f"{_BASE_URL}/captcha", {"token": challenge.token or "", "answer": answer}

    def detect_challenge(self, resp: FetchResponse) -> Challenge | None:
        """Thêm đề bài (mã hiển thị trên trang) và `token` cho luồng nhập đáp án của mock-shop."""
        challenge = super().detect_challenge(resp)
        if challenge is None or challenge.kind is not ChallengeKind.captcha:
            return challenge
        box = LexborHTMLParser(resp.text).css_first("div#captcha")
        if box is None:
            return challenge
        code = node_text(box)
        return challenge.model_copy(
            update={
                "prompt": f"Nhập mã xác minh hiển thị trên trang: {code}" if code else None,
                "token": box.attributes.get("data-token"),
            }
        )
