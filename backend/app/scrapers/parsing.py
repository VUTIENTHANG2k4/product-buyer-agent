"""Hàm parse HTML dùng chung cho các scraper (thuần, không I/O)."""

import json
import logging
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.domain.enums import StockStatus
from app.normalize.price import parse_price

logger = logging.getLogger(__name__)

_LD_SELECTOR = 'script[type="application/ld+json"]'


def json_ld_objects(tree: LexborHTMLParser) -> list[dict[str, Any]]:
    """Mọi đối tượng JSON-LD (phẳng hóa danh sách và `@graph`); khối JSON hỏng bị bỏ qua."""
    found: list[dict[str, Any]] = []
    for script in tree.css(_LD_SELECTOR):
        try:
            data = json.loads(script.text())
        except (ValueError, RecursionError):  # JSON hỏng hoặc lồng quá sâu
            logger.warning("JSON-LD không hợp lệ, bỏ qua")
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            found.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                found.extend(node for node in graph if isinstance(node, dict))
    return found


def node_text(node: LexborNode | None) -> str:
    """Văn bản của `node` với mọi chuỗi khoảng trắng/xuống dòng gộp thành một dấu cách.

    Giữ nguyên khoảng trắng giữa các thẻ inline (`Chuột <b>Razer</b> <i>Viper</i>`), không chèn
    thêm giữa chữ liền nhau (`Chu<b>ột</b>`). Chuỗi rỗng nếu không có node.
    """
    return " ".join(node.text().split()) if node is not None else ""


_AVAILABILITY: dict[str, StockStatus] = {
    "instock": StockStatus.in_stock,
    "limitedavailability": StockStatus.in_stock,
    "instoreonly": StockStatus.in_stock,
    "onlineonly": StockStatus.in_stock,
    "outofstock": StockStatus.out_of_stock,
    "soldout": StockStatus.out_of_stock,
    "discontinued": StockStatus.out_of_stock,
    "preorder": StockStatus.preorder,
    "presale": StockStatus.preorder,
    "backorder": StockStatus.preorder,
}


def schema_offer(product: dict[str, Any]) -> dict[str, Any]:
    """Khối `offers` của JSON-LD `Product` (đối tượng hoặc phần tử đầu); không có thì `{}`."""
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = next((o for o in offers if isinstance(o, dict)), None)
    return offers if isinstance(offers, dict) else {}


def schema_price(value: object) -> int | None:
    """Giá trong JSON-LD (số hoặc chuỗi số) → VND nguyên trong miền hợp lệ, ngược lại `None`."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return parse_price(int(value)) if value.is_integer() else None
    if isinstance(value, int | str):
        return parse_price(value)
    return None


def schema_stock(offer: dict[str, Any]) -> StockStatus:
    """`availability` của schema.org (URL hoặc tên) → `StockStatus`; không rõ → `unknown`."""
    availability = offer.get("availability")
    if not isinstance(availability, str):
        return StockStatus.unknown
    return _AVAILABILITY.get(availability.rsplit("/", 1)[-1].lower(), StockStatus.unknown)
