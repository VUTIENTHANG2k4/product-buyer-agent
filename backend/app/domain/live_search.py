"""DTO kết quả tìm trực tiếp tầng 2 (docs/05 §3, docs/03 §5.3). Tiền là `int` VND."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.dto import NonEmptyStr, Vnd
from app.domain.enums import SiteKey


class LiveSearchItem(BaseModel):
    """Một kết quả chưa chuẩn hóa: tên, giá, link và thời điểm tìm (UTC); không phải `Product`."""

    model_config = ConfigDict(frozen=True)

    site: SiteKey
    title: NonEmptyStr
    price: Vnd | None = None  # None nếu trang không hiện giá đọc được
    url: NonEmptyStr
    scraped_at: datetime


class SkippedSite(BaseModel):
    """Trang không được tìm trong lượt này kèm lý do tiếng Việt cho người dùng."""

    model_config = ConfigDict(frozen=True)

    site: SiteKey
    reason: NonEmptyStr


class LiveSearchResult(BaseModel):
    """Kết quả một lượt tìm: các trang đã tìm, trang bị bỏ qua và nhãn `unnormalized`."""

    model_config = ConfigDict(frozen=True)

    items: list[LiveSearchItem]
    sites_searched: list[SiteKey]
    sites_skipped: list[SkippedSite]
    from_cache: bool  # true khi mọi trang đã tìm đều lấy từ cache
    label: Literal["unnormalized"] = "unnormalized"
