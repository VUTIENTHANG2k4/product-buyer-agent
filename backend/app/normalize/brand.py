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
    ("HyperX", ("hyperx", "hp hyperx")),  # trước HP: "HP HyperX Cloud…" là tai nghe HyperX
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
    ("Akko", ("akko",)),
    ("DareU", ("dareu", "dare-u", "dare u")),
    ("E-Dra", ("e-dra", "edra")),
    ("Rapoo", ("rapoo",)),
    ("Keychron", ("keychron",)),
    ("Edifier", ("edifier",)),
    ("JBL", ("jbl",)),
    ("Anker", ("anker",)),
    ("AULA", ("aula",)),
    ("ATK", ("atk",)),
    ("Pulsar", ("pulsar",)),
    ("MCHOSE", ("mchose",)),
    ("HyperWork", ("hyperwork",)),
    ("Mionix", ("mionix",)),
    ("Microsoft", ("microsoft",)),
    ("Elecom", ("elecom",)),
    ("E-Blue", ("e-blue", "eblue")),
    ("Mofii", ("mofii",)),
    ("LG", ("lg",)),
    ("Thunderobot", ("thunderobot",)),
    ("Jabra", ("jabra",)),
    ("Blaupunkt", ("blaupunkt",)),
)

# Nhãn khuyến mãi ở đầu tên: "[Mới 100%] ...", "(Hàng chính hãng) ..."
_LEADING_TAGS = re.compile(r"^(?:\s*(?:\[[^\]]*\]|\([^)]*\)))+\s*")
# Ký hiệu trang trí đầu dòng ("★ Laptop …", "🔥 Laptop …"): không phải chữ hay số.
_LEADING_SYMBOLS = re.compile(r"^[^\w\[(]+")
# Mô tả loại/tính năng đứng trước hãng ("Chuột có dây Dell", "Hàng chính hãng Chuột Logitech",
# "Máy tính xách tay ASUS") có nhiều dạng nên không liệt kê: nếu tên BẮT ĐẦU bằng một từ loại sản
# phẩm (`_TYPE_STARTS`) thì được bỏ qua tối đa `MAX_SKIPPED` từ đầu để tìm hãng. Tên bắt đầu bằng
# từ khác ("Ốp lưng iPhone", "Túi chống sốc Laptop Dell") chỉ khớp khi hãng đứng ngay đầu. Dừng ở
# từ nối cho thấy hãng đứng sau là sản phẩm khác ("Bàn phím cho MacBook").
MAX_SKIPPED = 7
_TYPE_STARTS = frozenset(
    [
        "laptop",
        "may",
        "chuot",
        "mouse",
        "ban",
        "keyboard",
        "tai",
        "headset",
        "micro",
        "combo",
        "bo",
        "hang",
        "gaming",
        "game",
        "co",
        "khong",
        "cong",
        "true",
        "bluetooth",
        "silent",
        "mechanical",
        "wireless",
        "pc",
    ]
)
# Từ phụ kiện ở phần mô tả bị bỏ qua: "Bộ sạc laptop Dell 65W" là sạc, không phải laptop Dell.
_ACCESSORY_WORDS = frozenset(
    ["sac", "cap", "pin", "tui", "balo", "op", "lot", "de", "dock", "hub", "adapter"]
)
_CONNECTORS = frozenset(
    ["cho", "danh", "dung", "cua", "for", "phu", "tuong", "thich", "kem", "voi", "with"]
)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(alias)}(?![a-z0-9])")


_PATTERNS = tuple(
    (name, tuple(_alias_pattern(_fold(alias)) for alias in aliases)) for name, aliases in _BRANDS
)


def _brand_at(text: str) -> str | None:
    for name, patterns in _PATTERNS:
        if any(pattern.match(text) for pattern in patterns):
            return name
    return None


def find_brand(keys: list[str], *, typed: bool = False) -> tuple[int, str] | None:
    """(chỉ số từ bắt đầu hãng, tên hãng chuẩn) trong các từ đã `fold`, `None` nếu không có.

    Hãng đứng ngay đầu tên, hoặc nằm trong `MAX_SKIPPED + 1` từ đầu khi tên bắt đầu bằng từ loại
    sản phẩm hoặc khi nơi gọi đã biết nhóm (`typed`, ví dụ laptop đã bỏ chữ "Laptop"); không có từ
    nối đứng trước nó.
    """
    if not keys:
        return None
    reach = MAX_SKIPPED + 1 if typed or keys[0] in _TYPE_STARTS else 1
    for index in range(min(len(keys), reach)):
        if keys[index] in _CONNECTORS or keys[index] in _ACCESSORY_WORDS:
            return None
        brand = _brand_at(" ".join(keys[index:]))
        if brand is not None:
            return index, brand
    return None


def strip_leading_decoration(text: str) -> str:
    """Bỏ nhãn `[..]`/`(..)` và ký hiệu trang trí ở đầu tên, theo mọi thứ tự ("🔥 [Hot] …")."""
    while True:
        stripped = _LEADING_SYMBOLS.sub("", _LEADING_TAGS.sub("", text))
        if stripped == text:
            return text
        text = stripped


def detect_brand(title: str) -> str:
    """Tên hãng chuẩn nếu `title` có hãng đã biết ngay sau vài từ mô tả loại sản phẩm đầu tên
    ("Laptop", "Chuột có dây", "Hàng chính hãng Chuột"); không nhận ra thì `UNKNOWN_BRAND`.

    Chỉ nhìn phần đầu tên và dừng ở từ nối để "Bàn phím cho MacBook" không bị gán nhầm cho Apple.
    """
    text = strip_leading_decoration(_fold(title))
    found = find_brand(text.split())
    return UNKNOWN_BRAND if found is None else found[1]


# Cách viết tên công ty ngoài tên chuẩn: "HP HyperX Cloud…", "Logi MX…", "Dare-U EK87".
_COMPANY_EXTRA: dict[str, tuple[str, ...]] = {
    "HyperX": ("hp",),
    "Logitech": ("logi",),
    "DareU": ("dare-u",),
}


def brand_words(brand: str) -> frozenset[str]:
    """Các từ (đã `fold`) chỉ tên công ty của `brand`, để bỏ khỏi tên khi so sánh hai sản phẩm."""
    return frozenset({_fold(brand), *_COMPANY_EXTRA.get(brand, ())})
