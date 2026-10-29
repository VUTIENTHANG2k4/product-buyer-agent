"""Đồng hồ dùng chung: thời gian lưu UTC. Ở `domain` để mọi lớp dùng được (docs/03 §4)."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Thời điểm hiện tại theo UTC (có timezone); test thay bằng đồng hồ giả (time-machine)."""
    return datetime.now(UTC)
