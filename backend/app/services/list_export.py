"""Xuất danh sách mua ra CSV (X3, docs/07 §3.4).

Hàm thuần: nhận `ShoppingListDetail` đã tính giá từ DB, trả văn bản CSV. UTF-8 có BOM để Excel
trên Windows hiện đúng tiếng Việt; tiền là số nguyên VND (không định dạng) để bảng tính còn tính
được. Chống CSV injection theo OWASP: mọi ô được bọc nháy kép và ô văn bản bắt đầu bằng ký tự
công thức được thêm tiền tố `'`. Tên sản phẩm lấy từ web và ghi chú do người dùng nhập đều là dữ
liệu, không phải công thức.
"""

import csv
import io

from app.domain.catalog import ShoppingListDetail

BOM = chr(0xFEFF)  # byte order mark UTF-8 cho Excel
HEADER = (
    "STT",
    "Sản phẩm",
    "Số lượng",
    "Giá lúc thêm",
    "Giá hiện tại",
    "Chênh lệch",
    "Thành tiền",
    "Trang",
    "Link",
    "Ghi chú",
)
TOTAL_LABEL = "Tổng"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str | None) -> str:
    """Ô văn bản an toàn cho bảng tính: rỗng nếu `None`, thêm `'` nếu mở đầu như công thức."""
    if not value:
        return ""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def _number(value: int | None) -> str:
    return "" if value is None else str(value)


def export_filename(list_id: int) -> str:
    return f"danh-sach-{list_id}.csv"


def render_list_csv(detail: ShoppingListDetail) -> str:
    buffer = io.StringIO()
    # Bọc nháy kép mọi ô: Excel vùng Việt Nam tách cột theo `;`, ô không bọc như `a;=CMD()` sẽ tách
    # ra một ô mở đầu bằng `=` mà tiền tố `'` không che được (BUG-X3-1).
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow(HEADER)
    for position, item in enumerate(detail.items, start=1):
        available = item.current_price is not None
        offer = item.best_offer if available else None
        line_total = item.quantity * item.current_price if item.current_price is not None else None
        writer.writerow(
            (
                str(position),
                safe_text(item.name),
                str(item.quantity),
                _number(item.price_at_add),
                _number(item.current_price),
                _number(item.price_delta if available else None),
                _number(line_total),
                offer.site.value if offer is not None else "",
                safe_text(offer.url) if offer is not None else "",
                safe_text(item.note),
            )
        )
    writer.writerow((TOTAL_LABEL, "", "", "", "", "", str(detail.total_price), "", "", ""))
    return BOM + buffer.getvalue()
