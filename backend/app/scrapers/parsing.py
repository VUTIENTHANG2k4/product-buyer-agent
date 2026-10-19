"""Hàm parse HTML dùng chung cho các scraper (thuần, không I/O)."""

import json
import logging
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

logger = logging.getLogger(__name__)

_LD_SELECTOR = 'script[type="application/ld+json"]'


def json_ld_objects(tree: LexborHTMLParser) -> list[dict[str, Any]]:
    """Mọi đối tượng JSON-LD (phẳng hóa danh sách); khối JSON hỏng bị bỏ qua."""
    found: list[dict[str, Any]] = []
    for script in tree.css(_LD_SELECTOR):
        try:
            data = json.loads(script.text())
        except ValueError:
            logger.warning("JSON-LD không hợp lệ, bỏ qua")
            continue
        found.extend(
            item for item in (data if isinstance(data, list) else [data]) if isinstance(item, dict)
        )
    return found


def node_text(node: LexborNode | None) -> str:
    """Văn bản đã cắt khoảng trắng của `node`; chuỗi rỗng nếu không có node."""
    return node.text(strip=True) if node is not None else ""
