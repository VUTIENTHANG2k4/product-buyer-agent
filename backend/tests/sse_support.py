"""Đọc thân `text/event-stream` thành danh sách sự kiện cho test."""

import json
from typing import Any


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Mỗi khối cách nhau dòng trống -> {"event", "id", "data" (đã giải mã JSON)}. Bỏ comment."""
    events: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        fields: dict[str, Any] = {}
        data_lines: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if name == "data":
                data_lines.append(value)
            else:
                fields[name] = value
        if data_lines:
            fields["data"] = json.loads("\n".join(data_lines))
        if fields:
            events.append(fields)
    return events
