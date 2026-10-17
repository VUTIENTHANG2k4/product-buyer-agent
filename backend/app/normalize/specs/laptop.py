"""Khung thông số laptop (docs/04 §5.1)."""

from typing import Final, Self

from pydantic import BaseModel, computed_field, model_validator

from app.domain.dto import NonEmptyStr
from app.normalize.specs.gpu_rank import gpu_rank as lookup_gpu_rank
from app.normalize.specs.gpu_rank import normalize_gpu_name
from app.normalize.specs.types import Count, CpuVendor, PositiveFloat, PositiveInt, StorageType

# Thiếu (None) một trong các trường này thì laptop không dùng được trong lọc tầng 1.
REQUIRED_FIELDS: Final = ("cpu_model", "gpu_model", "ram_gb", "storage_gb")


class LaptopSpecs(BaseModel):
    """Mọi trường tùy chọn khi parse.

    `gpu_rank` là trường dẫn xuất chỉ đọc, tính từ `gpu_model` mỗi lần truy cập (nên không bao giờ
    cũ khi `gpu_model` bị gán lại). Nó có trong `model_dump()` để lọc JSONB; giá trị `gpu_rank`
    truyền vào khi parse bị bỏ qua.
    """

    cpu_model: NonEmptyStr | None = None
    cpu_vendor: CpuVendor | None = None
    gpu_model: NonEmptyStr | None = None
    gpu_vram_gb: Count | None = None  # 0 hợp lệ: GPU tích hợp không có VRAM riêng
    ram_gb: PositiveInt | None = None
    storage_gb: PositiveInt | None = None
    storage_type: StorageType | None = None
    screen_in: PositiveFloat | None = None
    resolution: NonEmptyStr | None = None
    refresh_hz: PositiveInt | None = None
    panel: NonEmptyStr | None = None
    weight_kg: PositiveFloat | None = None
    os: NonEmptyStr | None = None
    is_gaming: bool | None = None  # quy tắc suy ra thuộc extractor (T5.1)

    @model_validator(mode="after")
    def _normalize_gpu_model(self) -> Self:
        """Đưa `gpu_model` về tên chuẩn nếu nhận ra (chuỗi lạ giữ nguyên)."""
        if self.gpu_model is not None:
            canonical = normalize_gpu_name(self.gpu_model)
            if canonical is not None:
                self.gpu_model = canonical
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gpu_rank(self) -> int | None:
        """Hạng GPU (docs/04 §5.6); None nếu không có `gpu_model` hoặc GPU chưa có hạng."""
        return lookup_gpu_rank(self.gpu_model)
