"""Dựng HTML của mock-shop: danh sách (JSON-LD + thẻ HTML), chi tiết, challenge.

Mỗi giá trị chèn vào HTML đều qua `html.escape`; JSON-LD qua `json.dumps` và thay `</` để không đóng
thẻ script sớm.
"""

import json
from collections.abc import Sequence
from html import escape
from typing import Any

from app.mock_shop.catalog import MockProduct

IN_STOCK = "https://schema.org/InStock"
OUT_OF_STOCK = "https://schema.org/OutOfStock"
CATEGORY_TITLES = {
    "laptop": "Laptop",
    "mouse": "Chuột",
    "keyboard": "Bàn phím",
    "headset": "Tai nghe",
}


def format_vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "₫"


def _json_ld(data: dict[str, Any]) -> str:
    body = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'


def _document(title: str, head: str, body: str) -> str:
    return (
        '<!doctype html>\n<html lang="vi">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n{head}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def _product_ld(base: str, product: MockProduct) -> dict[str, Any]:
    data: dict[str, Any] = {
        "@type": "Product",
        "name": product.name,
        "sku": product.sku,
        "mpn": product.sku,
        "brand": {"@type": "Brand", "name": product.brand},
        "image": f"{base}/static/{product.slug}.jpg",
        "url": f"{base}/p/{product.slug}",
    }
    if product.price is not None:
        data["offers"] = {
            "@type": "Offer",
            "priceCurrency": "VND",
            "price": product.price,
            "availability": IN_STOCK if product.in_stock else OUT_OF_STOCK,
            "url": f"{base}/p/{product.slug}",
        }
    if product.rating is not None and product.rating_count > 0:
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": product.rating,
            "reviewCount": product.rating_count,
        }
    return data


def _price_html(product: MockProduct) -> str:
    if product.price is None:
        return '<span class="price price-contact">Liên hệ</span>'
    html = f'<span class="price">{format_vnd(product.price)}</span>'
    if product.list_price is not None and product.list_price > product.price:
        html += f' <span class="old-price">{format_vnd(product.list_price)}</span>'
    return html


def _card(product: MockProduct) -> str:
    stock = (
        '<span class="stock in-stock">Còn hàng</span>'
        if product.in_stock
        else '<span class="stock out-of-stock">Hết hàng</span>'
    )
    rating = (
        f'<span class="rating" data-rating="{product.rating}" data-count="{product.rating_count}">'
        f"{product.rating} ({product.rating_count})</span>"
        if product.rating is not None
        else ""
    )
    mini = "".join(
        f"<li>{escape(label)}: {escape(value)}</li>"
        for label, value in list(product.specs.items())[:3]
    )
    return (
        f'<li class="product-card" data-slug="{escape(product.slug)}" '
        f'data-sku="{escape(product.sku)}">'
        f'<a class="product-link" href="/p/{escape(product.slug)}">'
        f'<img src="/static/{escape(product.slug)}.jpg" alt="">'
        f'<h2 class="product-name">{escape(product.name)}</h2></a>'
        f"{_price_html(product)} {stock} {rating}"
        f'<ul class="mini-specs">{mini}</ul></li>'
    )


def listing_page(
    base: str,
    heading: str,
    products: Sequence[MockProduct],
    *,
    prev_href: str | None = None,
    next_href: str | None = None,
) -> str:
    """Trang danh sách/tìm kiếm. `next_href` có mặt khi còn trang sau (nút "Trang sau")."""
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {"@type": "ListItem", "position": index, "item": _product_ld(base, product)}
            for index, product in enumerate(products, start=1)
        ],
    }
    cards = "\n".join(_card(product) for product in products)
    nav = ""
    if prev_href:
        nav += f'<a rel="prev" href="{escape(prev_href)}">Trang trước</a> '
    if next_href:
        nav += f'<a rel="next" href="{escape(next_href)}">Trang sau</a>'
    body = (
        f"<h1>{escape(heading)}</h1>\n"
        f'<ul class="products">\n{cards}\n</ul>\n'
        f'<nav class="pagination">{nav}</nav>'
    )
    return _document(f"{heading} | Mock Shop", _json_ld(item_list), body)


def detail_page(base: str, product: MockProduct) -> str:
    product_ld = {"@context": "https://schema.org", **_product_ld(base, product)}
    rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in product.specs.items()
    )
    stock = "Còn hàng" if product.in_stock else "Hết hàng"
    body = (
        f'<h1 class="product-name">{escape(product.name)}</h1>\n'
        f'{_price_html(product)} <span class="stock">{stock}</span>\n'
        f'<p class="sku">Mã: {escape(product.sku)}</p>\n'
        f'<table class="specs">\n{rows}\n</table>'
    )
    return _document(f"{product.name} | Mock Shop", _json_ld(product_ld), body)


def not_found_page(message: str) -> str:
    return _document("Không tìm thấy | Mock Shop", "", f"<h1>404</h1><p>{escape(message)}</p>")


def challenge_page(code: str, token: str) -> str:
    """Trang captcha giả: mã 5 ký tự dạng chữ (không phải ảnh), form POST /captcha."""
    body = (
        "<h1>Xác minh bạn không phải robot</h1>\n"
        f'<div id="captcha" data-token="{escape(token)}">{escape(code)}</div>\n'
        '<form method="post" action="/captcha">\n'
        f'<input type="hidden" name="token" value="{escape(token)}">\n'
        '<input name="answer" autocomplete="off">\n'
        '<button type="submit">Gửi</button>\n</form>'
    )
    return _document("Xác minh | Mock Shop", "", body)


def captcha_result_page(ok: bool) -> str:
    message = "Xác minh thành công." if ok else "Mã chưa đúng, hãy thử lại."
    return _document("Xác minh | Mock Shop", "", f"<p>{message}</p>")
