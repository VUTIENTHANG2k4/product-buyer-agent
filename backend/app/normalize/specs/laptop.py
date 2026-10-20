"""Khung thông số laptop (docs/04 §5.1) và bộ trích xuất theo luật (docs/04 §7)."""

import re
from collections.abc import Mapping
from typing import Final, Self

from pydantic import BaseModel, computed_field, model_validator

from app.domain.dto import NonEmptyStr
from app.normalize.specs.gpu_rank import INTEGRATED, normalize_gpu_name
from app.normalize.specs.gpu_rank import gpu_rank as lookup_gpu_rank
from app.normalize.specs.parsing import (
    build_specs,
    capacities_gb,
    clean,
    first_capacity_gb,
    has_word,
    label_values,
    parse_hertz,
    parse_inches,
    parse_kilograms,
)
from app.normalize.specs.types import Count, CpuVendor, PositiveFloat, PositiveInt, StorageType
from app.normalize.text import fold

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
    is_gaming: bool | None = None  # quy tắc suy ra: xem `extract_laptop`

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


# ---- bộ trích xuất theo luật ----
# Bí danh nhãn bảng thông số (đã `fold`): GearVN ("Dung lượng RAM"), An Phát ("Bộ nhớ trong (RAM) /
# Dung lượng", "VGA"), FPT Shop ("CPU", "Card đồ hoạ"). Thứ tự = ưu tiên.
_CPU_LABELS: Final = ("cpu", "bo vi xu ly", "processor")
_CPU_FAMILY_LABELS: Final = ("dong cpu",)
_GPU_LABELS: Final = ("card do hoa", "card man hinh", "vga", "do hoa", "gpu")
_RAM_LABELS: Final = ("dung luong ram", "bo nho trong (ram) / dung luong", "ram")
_STORAGE_LABELS: Final = (
    "dung luong ssd",
    "o cung / dung luong",
    "dung luong luu tru",
    "o cung",
    "ssd",
)
_SCREEN_LABELS: Final = ("kich thuoc man hinh", "hien thi / man hinh", "man hinh")
_RESOLUTION_LABELS: Final = ("do phan giai", "man hinh")
_REFRESH_LABELS: Final = ("tan so quet", "cong nghe man hinh", "man hinh")
_PANEL_LABELS: Final = ("tam nen", "cong nghe man hinh", "man hinh")
_WEIGHT_LABELS: Final = ("can nang", "trong luong")
_OS_LABELS: Final = ("he dieu hanh", "os")
_GROUP_LABELS: Final = ("nhom thuoc tinh",)

_TRADEMARKS = re.compile(r"[™®℠]")
_FLAGS = re.IGNORECASE

# (regex, định dạng). Thứ tự quan trọng: "Core Ultra" trước "Core N" trước "i-series".
_CORE_ULTRA = re.compile(
    r"\b(?:core\s*)?ultra\s*([3579])\s*[-–]?\s*(?:processor\s+)?(\d{3}[a-z]{0,2})\b", _FLAGS
)
_CORE_NEW = re.compile(r"\bcore\s*([3579])\s*[-–]?\s*(\d{3}[a-z]{0,2})\b", _FLAGS)
_CORE_I = re.compile(r"\bi([3579])\s*[-–]?\s*(\d{4,5}[a-z]{0,2})\b", _FLAGS)
_RYZEN = re.compile(
    r"\bryzen\s*(ai\s*)?([3579])\s*[-–]?\s*(?:pro\s+)?((?:hx\s*)?\d{2,5}[a-z]{0,3}\d?)"
    r"(?![0-9]|\s?gb)\b",
    _FLAGS,
)
_RYZEN_SHORT = re.compile(r"\br([3579])[\s-]?(\d{4}[a-z]{0,2})\b", _FLAGS)
_SNAPDRAGON = re.compile(
    r"\bsnapdragon\s+x(?:\s+(plus|elite))?(?:\s+(x[0-9a-z]+(?:-\d+)*))?\b", _FLAGS
)
_APPLE = re.compile(r"\bm([1-4])(?:\s+(pro|max|ultra))?\b", _FLAGS)
_BUDGET_CPU = re.compile(
    r"\b(celeron|pentium|athlon)\s+(?:silver\s+|gold\s+)?([a-z]?\d{3,5}[a-z]?)\b", _FLAGS
)
_CPU_FAMILY_HINT = re.compile(
    r"core|ryzen|ultra|snapdragon|apple|celeron|pentium|\bi[3579]\b", _FLAGS
)

_DISCRETE_WITH_VRAM = re.compile(
    r"(?:rtx|gtx|rx)\s*-?\s*\d{3,4}[ms]?"
    r"(?:[\s,(:-]+(?:ti|super|xtx?|laptop|gpu|gddr\d+x?|nvidia|geforce|dedicated))*"
    r"[\s,(:-]*(\d{1,2})\s?gb\b",
    _FLAGS,
)
_TITLE_ONBOARD = re.compile(r"\bon-?board\b(?!\s*(?:graphics|vga|gpu|card))", re.IGNORECASE)
# GPU tích hợp mà `normalize_gpu_name` chưa nhận (Intel Arc không hậu tố, "AMD Radeon" trơn…).
_INTEGRATED_EXTRA = re.compile(
    r"\b(?:intel\s+arc|amd\s+radeon|radeon\s+vega|vega\s*\d|adreno|intel\s+iris|intel\s+graphics)\b",
    _FLAGS,
)

# Chỉ đổi độ phân giải khi chắc chắn (WxH ghi rõ hoặc tên chuẩn một nghĩa). "2K", "2.5K", "3K",
# "QHD" mỗi nhà sản xuất hiểu một kiểu nên để trống.
_EXPLICIT_RESOLUTION = re.compile(r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b", _FLAGS)
_NAMED_RESOLUTIONS: Final = (
    (re.compile(r"\bwuxga\b|\bfhd\s*\+", _FLAGS), "1920x1200"),
    (re.compile(r"\bfhd\b|\bfull\s*hd\b", _FLAGS), "1920x1080"),
    (re.compile(r"\bwqxga\b", _FLAGS), "2560x1600"),
    (re.compile(r"\b4k\b|\buhd\b(?!\s*graphics)", _FLAGS), "3840x2160"),
)
_PANEL = re.compile(r"\b(amoled|oled|mini[\s-]?led|ips|va|tn)\b", _FLAGS)
_OS = re.compile(r"\bwin(?:dows)?\s*(11|10)\s*(home|pro)?\b", _FLAGS)
_OTHER_OS = (
    (re.compile(r"\bfree\s*dos\b|\bno\s*os\b|\bdos\b", _FLAGS), "FreeDOS"),
    (re.compile(r"\bmacos\b", _FLAGS), "macOS"),
    (re.compile(r"\blinux\b|\bubuntu\b", _FLAGS), "Linux"),
)
_VRAM_MAX_GB: Final = 32


def _cpu(text: str) -> tuple[str, CpuVendor] | None:
    """(tên CPU chuẩn, hãng) đọc từ `text`; `None` nếu không nhận ra mã CPU cụ thể."""
    text = _TRADEMARKS.sub(" ", text)
    if match := _CORE_ULTRA.search(text):
        return f"Core Ultra {match[1]} {match[2].upper()}", CpuVendor.intel
    if match := _CORE_NEW.search(text):
        return f"Core {match[1]} {match[2].upper()}", CpuVendor.intel
    if match := _CORE_I.search(text):
        return f"i{match[1]}-{match[2].upper()}", CpuVendor.intel
    if match := _RYZEN.search(text):
        ai = "AI " if match[1] else ""
        return f"Ryzen {ai}{match[2]} {' '.join(match[3].upper().split())}", CpuVendor.amd
    if match := _SNAPDRAGON.search(text):
        parts = ["Snapdragon X", (match[1] or "").title(), (match[2] or "").upper()]
        return " ".join(part for part in parts if part), CpuVendor.qualcomm
    if "ryzen" not in text.lower() and (match := _RYZEN_SHORT.search(text)):
        return f"Ryzen {match[1]} {match[2].upper()}", CpuVendor.amd
    if match := _BUDGET_CPU.search(text):
        vendor = CpuVendor.amd if match[1].lower() == "athlon" else CpuVendor.intel
        return f"{match[1].title()} {match[2].upper()}", vendor
    lowered = text.lower()
    if ("macbook" in lowered or "apple" in lowered) and (match := _APPLE.search(text)):
        suffix = f" {match[2].title()}" if match[2] else ""
        return f"Apple M{match[1]}{suffix}", CpuVendor.apple
    return None


def _vendor_of(cpu_model: str) -> CpuVendor | None:
    lowered = cpu_model.lower()
    if lowered.startswith(("ryzen", "athlon")):
        return CpuVendor.amd
    if lowered.startswith("snapdragon"):
        return CpuVendor.qualcomm
    if lowered.startswith("apple"):
        return CpuVendor.apple
    if lowered.startswith(("core", "i3", "i5", "i7", "i9", "celeron", "pentium")):
        return CpuVendor.intel
    return None


def _extract_cpu(title: str, raw_specs: Mapping[str, str]) -> tuple[str, CpuVendor | None] | None:
    found = _cpu(title)
    if found is not None:
        return found
    for value in label_values(raw_specs, _CPU_LABELS):
        found = _cpu(value)
        if found is not None:
            return found
    # Chỉ có tên dòng ("Core 5", "Ryzen 7"): vẫn hữu ích hơn để trống.
    for value in (
        *label_values(raw_specs, _CPU_FAMILY_LABELS),
        *label_values(raw_specs, _CPU_LABELS),
    ):
        if len(value) <= 40 and _CPU_FAMILY_HINT.search(value):
            return value, _vendor_of(value)
    return None


def _gpu(text: str) -> str | None:
    """Tên GPU chuẩn trong `text` (`Integrated` cho GPU tích hợp); `None` nếu không nhận ra."""
    name = normalize_gpu_name(text)
    if name is not None:
        return name
    return INTEGRATED if _INTEGRATED_EXTRA.search(text) else None


def _extract_gpu(title: str, raw_specs: Mapping[str, str]) -> tuple[str | None, int | None]:
    """(tên GPU, VRAM GB). Nhãn bảng thông số được ưu tiên hơn tiêu đề."""
    # "16GB onboard" trong tiêu đề nói về RAM; chỉ "onboard graphics/VGA/GPU" mới nói về GPU.
    title = _TITLE_ONBOARD.sub(" ", title)
    for source in (*label_values(raw_specs, _GPU_LABELS), title):
        name = _gpu(source)
        if name is None:
            continue
        if name == INTEGRATED:
            return name, None
        vram = _DISCRETE_WITH_VRAM.search(_TRADEMARKS.sub(" ", source))
        size = int(vram[1]) if vram else None
        return name, size if size is not None and 0 < size <= _VRAM_MAX_GB else None
    return None, None


def _split_memory(title: str) -> tuple[int | None, int | None]:
    """(RAM GB, ổ cứng GB) từ tiêu đề: dung lượng ≤ 64 GB đứng trước là RAM, còn lại là ổ cứng."""
    sizes = capacities_gb(_DISCRETE_WITH_VRAM.sub(" | ", title))
    if len(sizes) >= 2:
        first, second = sizes[0], sizes[1]
        return (second, first) if first > 64 >= second else (first, second)
    if len(sizes) == 1:
        return (sizes[0], None) if sizes[0] <= 64 else (None, sizes[0])
    return None, None


def _label_capacity(raw_specs: Mapping[str, str], aliases: tuple[str, ...]) -> int | None:
    for value in label_values(raw_specs, aliases):
        size = first_capacity_gb(value)
        if size is not None:
            return size
    return None


def _resolution(text: str) -> str | None:
    explicit = _EXPLICIT_RESOLUTION.search(text)
    if explicit is not None:
        return f"{explicit[1]}x{explicit[2]}"
    for pattern, value in _NAMED_RESOLUTIONS:
        if pattern.search(text):
            return value
    return None


def _first(values: list[str | None]) -> str | None:
    return next((value for value in values if value), None)


def _panel(text: str) -> str | None:
    match = _PANEL.search(text)
    if match is None:
        return None
    word = match[1].lower().replace(" ", "").replace("-", "")
    return {"oled": "OLED", "amoled": "AMOLED", "miniled": "Mini LED"}.get(word, word.upper())


def _os(text: str) -> str | None:
    match = _OS.search(text)
    if match is not None:
        edition = f" {match[2].title()}" if match[2] else ""
        return f"Windows {match[1]}{edition}"
    for pattern, name in _OTHER_OS:
        if pattern.search(text):
            return name
    return None


def _storage_type(*texts: str) -> StorageType | None:
    joined = " ".join(texts).lower()
    if re.search(r"\bssd\b|nvme|m\.2|pcie", joined):
        return StorageType.ssd
    if re.search(r"\bhdd\b", joined):
        return StorageType.hdd
    return None


def extract_laptop(title: str, raw_specs: Mapping[str, str]) -> LaptopSpecs:
    """Thông số laptop đọc được từ tiêu đề và bảng thông số thô; không đọc được thì để trống.

    Nhãn bảng thông số thắng tiêu đề với RAM, ổ cứng, GPU; `cpu_model` lấy từ tiêu đề trước vì
    nhãn thường chỉ ghi tên dòng. `is_gaming` đúng khi có GPU rời hoặc chữ "gaming", sai khi GPU
    tích hợp, còn lại để trống.
    """
    title = clean(title)
    cpu = _extract_cpu(title, raw_specs)
    gpu_model, vram = _extract_gpu(title, raw_specs)

    title_ram, title_storage = _split_memory(title)
    ram = _label_capacity(raw_specs, _RAM_LABELS) or title_ram
    storage = _label_capacity(raw_specs, _STORAGE_LABELS) or title_storage
    storage_label = next(label_values(raw_specs, _STORAGE_LABELS), "")

    inches = parse_inches(title)
    for value in label_values(raw_specs, _SCREEN_LABELS):
        if inches is not None:
            break
        inches = parse_inches(value)
    resolution = _resolution(title) or _first(
        [_resolution(value) for value in label_values(raw_specs, _RESOLUTION_LABELS)]
    )
    refresh = parse_hertz(title)
    for value in label_values(raw_specs, _REFRESH_LABELS):
        if refresh is not None:
            break
        refresh = parse_hertz(value)
    panel = _panel(title) or _first([_panel(v) for v in label_values(raw_specs, _PANEL_LABELS)])
    weight = next(
        (w for w in map(parse_kilograms, label_values(raw_specs, _WEIGHT_LABELS)) if w), None
    )
    os_name = _os(title) or _first([_os(v) for v in label_values(raw_specs, _OS_LABELS)])

    gaming_words = has_word(fold(title), "gaming") or any(
        has_word(fold(v), "gaming") for v in label_values(raw_specs, _GROUP_LABELS)
    )
    discrete = gpu_model is not None and gpu_model != INTEGRATED
    is_gaming: bool | None = True if (gaming_words or discrete) else None
    if is_gaming is None and gpu_model == INTEGRATED:
        is_gaming = False

    return build_specs(
        LaptopSpecs,
        {
            "cpu_model": cpu[0] if cpu else None,
            "cpu_vendor": cpu[1] if cpu else None,
            "gpu_model": gpu_model,
            "gpu_vram_gb": vram,
            "ram_gb": ram if ram is not None and ram <= 256 else None,
            "storage_gb": storage if storage is not None and storage >= 32 else None,
            "storage_type": _storage_type(storage_label, title),
            "screen_in": inches if inches is not None and 10 <= inches <= 20 else None,
            "resolution": resolution,
            "refresh_hz": refresh,
            "panel": panel,
            "weight_kg": weight,
            "os": os_name,
            "is_gaming": is_gaming,
        },
    )
