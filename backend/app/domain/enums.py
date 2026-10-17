"""Enum miền: giá trị khớp bảng ở docs/04 §4.

Trong CSDL, enum lưu `VARCHAR` + `CHECK` (ADR-0007), nên giá trị chuỗi là hợp đồng lưu trữ:
không đổi tên giá trị mà không có migration.
"""

from enum import StrEnum


class Category(StrEnum):
    laptop = "laptop"
    mouse = "mouse"
    keyboard = "keyboard"
    headset = "headset"
    phone = "phone"
    other = "other"


class SiteKey(StrEnum):
    gearvn = "gearvn"
    hoangha = "hoangha"
    laptop88 = "laptop88"
    viettelstore = "viettelstore"
    nguyenkim = "nguyenkim"
    mockshop = "mockshop"


class PriceType(StrEnum):
    regular = "regular"  # giá bán không giảm
    sale = "sale"  # giá khuyến mãi công khai
    member = "member"  # giá thành viên
    flash = "flash"  # flash sale đang diễn ra
    unknown = "unknown"


class StockStatus(StrEnum):
    in_stock = "in_stock"
    out_of_stock = "out_of_stock"
    preorder = "preorder"
    unknown = "unknown"


class ScrapeStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ScrapeTrigger(StrEnum):
    schedule = "schedule"
    manual = "manual"
    tracked_refresh = "tracked_refresh"
    test = "test"


class MatchMethod(StrEnum):
    model_code = "model_code"
    fuzzy = "fuzzy"
    new = "new"


class AlertChannel(StrEnum):
    email = "email"
    telegram = "telegram"


class AlertStatus(StrEnum):
    active = "active"
    triggered = "triggered"
    paused = "paused"


class AgentRunStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    needs_clarification = "needs_clarification"
    failed = "failed"
