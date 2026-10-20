"""Nhận diện hãng từ tên sản phẩm (docs/04 §7)."""

import re

from app.normalize.text import fold as _fold

UNKNOWN_BRAND = "Unknown"  # `product.brand` NOT NULL nên cần giá trị dự phòng

# (tên chuẩn, các cách viết khác). So khớp ở đầu tên, không phân biệt hoa thường và dấu.
_BRANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ASUS", ("asus", "rog", "tuf gaming", "zenbook", "vivobook")),
    ("Acer", ("acer", "predator", "nitro", "aspire", "swift")),
    ("Lenovo", ("lenovo", "thinkpad", "ideapad", "legion", "loq", "yoga")),
    ("MSI", ("msi",)),
    ("HP", ("hp", "hewlett packard", "victus", "omen", "pavilion")),
    ("Dell", ("dell", "alienware", "inspiron", "latitude", "xps")),
    ("Gigabyte", ("gigabyte", "aorus")),
    ("Apple", ("apple", "macbook", "iphone", "ipad")),
    ("Samsung", ("samsung", "galaxy")),
    ("Sony", ("sony",)),
    ("Logitech", ("logitech", "logi")),
    ("Razer", ("razer",)),
    ("Corsair", ("corsair",)),
    ("SteelSeries", ("steelseries",)),
    ("HyperX", ("hyperx",)),
    ("Akko", ("akko",)),
    ("DareU", ("dareu", "dare-u", "dare u")),
    ("E-Dra", ("e-dra", "edra")),
    ("Rapoo", ("rapoo",)),
    ("Keychron", ("keychron",)),
    ("Edifier", ("edifier",)),
    ("JBL", ("jbl",)),
    ("Anker", ("anker",)),
)

# Tiền tố loại sản phẩm/tính năng ở đầu tên (đã bỏ dấu), bỏ dần trước khi tìm hãng.
_PREFIX = re.compile(
    r"^(?:laptop|chuot|ban phim|tai nghe|co|gaming|game|khong day|mechanical|wireless)"
    r"(?![a-z0-9])\s*"
)


# Nhãn khuyến mãi ở đầu tên: "[Mới 100%] ...", "(Hàng chính hãng) ..."
_LEADING_TAGS = re.compile(r"^(?:\s*(?:\[[^\]]*\]|\([^)]*\)))+\s*")


def _alias_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(alias)}(?![a-z0-9])")


_PATTERNS = tuple(
    (name, tuple(_alias_pattern(_fold(alias)) for alias in aliases)) for name, aliases in _BRANDS
)


def detect_brand(title: str) -> str:
    """Tên hãng chuẩn nếu `title` bắt đầu bằng hãng đã biết (sau tiền tố loại sản phẩm như
    "Laptop"/"Chuột"); không nhận ra thì `UNKNOWN_BRAND`.

    Chỉ so khớp ở đầu tên để "Bàn phím cho MacBook" không bị gán nhầm cho Apple.
    """
    text = _LEADING_TAGS.sub("", _fold(title))
    for _ in range(4):  # bỏ lần lượt "Laptop gaming ..." / "Chuột không dây ..."
        stripped = _PREFIX.sub("", text)
        if stripped == text:
            break
        text = stripped
    for name, patterns in _PATTERNS:
        if any(pattern.match(text) for pattern in patterns):
            return name
    return UNKNOWN_BRAND
