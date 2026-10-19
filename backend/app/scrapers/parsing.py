"""Hàm parse HTML dùng chung cho các scraper (thuần, không I/O)."""

import json
import logging
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

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
