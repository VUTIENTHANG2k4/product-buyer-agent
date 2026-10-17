"""Chuẩn hóa tên GPU và xếp hạng GPU (docs/04 §5.6).

`GPU_RANKS` là thứ tự xấp xỉ do dự án tự định nghĩa để lọc kiểu "RTX 4060 trở lên", không phải
điểm benchmark. Thêm GPU mới = sửa bảng ở docs/04 §5.6, `GPU_RANKS` và test thứ tự trong cùng task.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

INTEGRATED: Final = "Integrated"

# Càng lớn càng mạnh. GPU không có trong bảng → `gpu_rank` trả None (không thỏa bộ lọc theo hạng).
GPU_RANKS: Final[Mapping[str, int]] = MappingProxyType(
    {
        INTEGRATED: 0,
        "RTX 2050": 10,
        "RTX 3050": 20,
        "RTX 3050 Ti": 22,
        "RTX 4050": 30,
        "RTX 3060": 32,
        "RTX 5050": 34,
        "RTX 4060": 40,
        "RTX 5060": 45,
        "RTX 4070": 50,
        "RTX 5070": 55,
        "RTX 5070 Ti": 60,
        "RTX 4080": 70,
        "RTX 5080": 75,
        "RTX 4090": 80,
        "RTX 5090": 85,
    }
)

# GPU rời: NVIDIA RTX (4 chữ số), GTX (3-4 chữ số), AMD RX (4 chữ số, hậu tố M/S, XT). `\b` đầu
# chặn khớp giữa từ; hậu tố Ti/Super phải đứng riêng từ nên "RTX 4060 TIGER" vẫn ra "RTX 4060". RTX
# workstation ("RTX 4000 Ada") bị loại bằng lookahead vì không phải dòng GeForce trong bảng hạng.
_DISCRETE = re.compile(
    r"\b(?:"
    r"(?P<rtx>rtx)[\s_-]*(?P<rtx_num>\d{4})(?!\s*ada\b)"
    r"|(?P<gtx>gtx)[\s_-]*(?P<gtx_num>\d{3,4})"
    r"|(?P<rx>rx)[\s_-]*(?P<rx_num>\d{4})(?P<rx_suffix>[ms])?"
    r")"
    r"(?:\s*(?P<ti>ti))?(?:\s*(?P<xt>xt))?(?:\s*(?P<super>super))?\b",
    re.IGNORECASE,
)

# GPU tích hợp phổ biến. Chỉ dùng khi không khớp GPU rời ("Radeon RX 7600M" là GPU rời). Arc rời
# ("Arc A370M") và MX ("GeForce MX550") cố ý không nằm đây: chưa có hạng, nên là `None`.
_INTEGRATED = re.compile(
    r"\b(?:integrated|on-?board|uhd|iris|intel\s+graphics|arc\s+graphics|radeon\s+graphics"
    r"|radeon\s+\d{3,4}[ms]|apple\s+m\d)\b",
    re.IGNORECASE,
)


def normalize_gpu_name(raw: str) -> str | None:
    """Đưa tên GPU thô về dạng chuẩn, ví dụ `"GeForce RTX4060 8GB"` → `"RTX 4060"`.

    Trả `None` nếu chuỗi không nhận ra là GPU, hoặc nhắc tới nhiều GPU rời khác nhau (mơ hồ, ví dụ
    `"RTX 4050 (up to RTX 4060)"`). Tên nhận ra nhưng chưa có hạng (GTX, RX, Super…) vẫn được chuẩn
    hóa; `gpu_rank` mới là nơi quyết định có hạng hay không.
    """
    text = re.sub(r"geforce|[™®]", " ", raw, flags=re.IGNORECASE)
    names = {_canonical(match) for match in _DISCRETE.finditer(text)}
    if len(names) == 1:
        return names.pop()
    if names:
        return None
    if _INTEGRATED.search(text) is not None:
        return INTEGRATED
    return None


def _canonical(match: re.Match[str]) -> str:
    if match["rtx"]:
        name = f"RTX {match['rtx_num']}"
    elif match["gtx"]:
        name = f"GTX {match['gtx_num']}"
    else:
        name = f"RX {match['rx_num']}{(match['rx_suffix'] or '').upper()}"
    for group, label in (("ti", "Ti"), ("xt", "XT"), ("super", "Super")):
        if match[group]:
            name = f"{name} {label}"
    return name


def gpu_rank(raw: str | None) -> int | None:
    """Hạng theo `GPU_RANKS` sau khi chuẩn hóa tên; `None` nếu không nhận ra hoặc chưa có hạng."""
    if raw is None:
        return None
    name = normalize_gpu_name(raw)
    return None if name is None else GPU_RANKS.get(name)
