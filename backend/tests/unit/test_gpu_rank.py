"""Chuẩn hóa tên GPU và `gpu_rank` (app/normalize/specs/gpu_rank.py, docs/04 §5.6)."""

import pytest

from app.normalize.specs.gpu_rank import GPU_RANKS, gpu_rank, normalize_gpu_name

# Bản chép nguyên văn bảng khởi tạo ở docs/04 §5.6: sửa bảng thì phải sửa cả test này.
DOC_TABLE = {
    "Integrated": 0,
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

# Thứ tự từ yếu đến mạnh theo nhóm đã thống nhất; mọi cặp liền kề phải tăng ngặt.
RANK_ORDER = [
    "Integrated",
    "RTX 2050",
    "RTX 3050",
    "RTX 3050 Ti",
    "RTX 4050",
    "RTX 3060",
    "RTX 5050",
    "RTX 4060",
    "RTX 5060",
    "RTX 4070",
    "RTX 5070",
    "RTX 5070 Ti",
    "RTX 4080",
    "RTX 5080",
    "RTX 4090",
    "RTX 5090",
]


def test_rank_table_matches_documented_values() -> None:
    assert dict(GPU_RANKS) == DOC_TABLE


def test_rank_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        GPU_RANKS["RTX 9999"] = 99  # type: ignore[index]


def test_rank_order_is_strictly_increasing() -> None:
    ranks = [GPU_RANKS[name] for name in RANK_ORDER]
    assert ranks == sorted(set(ranks))
    assert set(RANK_ORDER) == set(GPU_RANKS)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GeForce RTX4060 8GB", "RTX 4060"),
        ("RTX 4060", "RTX 4060"),
        ("rtx4050", "RTX 4050"),
        ("RTX-4070", "RTX 4070"),
        ("NVIDIA GeForce RTX 4060 8GB GDDR6", "RTX 4060"),
        ("NVIDIA® GeForce RTX™ 4060 Laptop GPU", "RTX 4060"),
        ("RTX 3050Ti", "RTX 3050 Ti"),
        ("RTX 3050 ti 4GB", "RTX 3050 Ti"),
        ("RTX 5070 Ti", "RTX 5070 Ti"),
        ("RTX 4060Ti", "RTX 4060 Ti"),
        ("RTX 4070 Super", "RTX 4070 Super"),
        ("RTX 4070 Ti Super", "RTX 4070 Ti Super"),
        ("RTX 4060 TIGER EDITION", "RTX 4060"),
        ("  rtx 2050  ", "RTX 2050"),
        ("GTX 1650", "GTX 1650"),
        ("GeForce GTX1650 4GB", "GTX 1650"),
        ("GTX 960", "GTX 960"),
        ("Radeon RX 7600M XT", "RX 7600M XT"),
        ("AMD Radeon RX 6600M", "RX 6600M"),
        ("Integrated", "Integrated"),
        ("Onboard", "Integrated"),
        ("Intel UHD Graphics", "Integrated"),
        ("Intel Iris Xe Graphics", "Integrated"),
        ("Intel Arc Graphics", "Integrated"),
        ("AMD Radeon Graphics", "Integrated"),
        ("AMD Radeon 780M", "Integrated"),
        ("RTX 4060 + Intel UHD Graphics", "RTX 4060"),
        ("GeForceRTX4060", "RTX 4060"),
        ("RTX_4060", "RTX 4060"),
        ("RTX 4060 / RTX 4060 8GB", "RTX 4060"),  # cùng một GPU nhắc hai lần không mơ hồ
        ("Radeon RX 6700S", "RX 6700S"),
        ("RX 6800S", "RX 6800S"),
        ("Apple M3 GPU", "Integrated"),
        ("Radeon 8060S", "Integrated"),
    ],
)
def test_normalize_gpu_name_returns_canonical_name(raw: str, expected: str) -> None:
    assert normalize_gpu_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "RTX",
        "RTX 40",
        "RTX 406",
        "RTX 40600",
        "GTX",
        "Core i7-13620H",
        "16GB DDR5",
        "Intel Arc A370M",  # Arc rời: chưa có hạng, cố ý không coi là tích hợp
        "GeForce MX550",
        "RTX 4000 Ada Generation",  # workstation, không thuộc dòng GeForce trong bảng
        "RTX 4050 6GB (up to RTX 4060)",  # nhiều GPU rời khác nhau → mơ hồ
        "RTX 4060 / RTX 4070",
    ],
)
def test_normalize_gpu_name_returns_none_for_non_gpu_text(raw: str) -> None:
    assert normalize_gpu_name(raw) is None


@pytest.mark.parametrize(("name", "rank"), sorted(DOC_TABLE.items()))
def test_gpu_rank_returns_documented_rank(name: str, rank: int) -> None:
    assert gpu_rank(name) == rank


def test_gpu_rank_normalizes_before_lookup() -> None:
    assert gpu_rank("GeForce RTX4060 8GB") == 40
    assert gpu_rank("rtx4050") == 30
    assert gpu_rank("Intel UHD Graphics") == 0


@pytest.mark.parametrize(
    "raw",
    ["RTX 4070 Ti", "RTX 4070 Super", "GTX 1650", "RX 7600M XT", "RTX 4060 Ti", "RTX 9999", "abc"],
)
def test_gpu_rank_is_none_when_gpu_not_in_table(raw: str) -> None:
    assert gpu_rank(raw) is None


def test_gpu_rank_is_none_for_missing_input() -> None:
    assert gpu_rank(None) is None
    assert gpu_rank("") is None


def test_rank_order_protects_intended_relations() -> None:
    assert gpu_rank("RTX 3060") > gpu_rank("RTX 4050")  # type: ignore[operator]
    assert gpu_rank("RTX 5050") < gpu_rank("RTX 4060")  # type: ignore[operator]
    assert gpu_rank("RTX 3050 Ti") > gpu_rank("RTX 3050")  # type: ignore[operator]
    assert gpu_rank("RTX 5070 Ti") > gpu_rank("RTX 5070")  # type: ignore[operator]
    assert gpu_rank("RTX 2050") > gpu_rank("Integrated")  # type: ignore[operator]
