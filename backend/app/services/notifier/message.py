"""Nội dung thông báo giá: chỉ dùng dữ liệu lấy từ CSDL (tên, giá, link nguồn)."""

from dataclasses import dataclass

from app.domain.enums import SiteKey


@dataclass(frozen=True)
class AlertMessage:
    subject: str
    body: str


def format_vnd(amount: int) -> str:
    """`27490000` → `27.490.000 ₫`."""
    return f"{amount:,}".replace(",", ".") + " ₫"


def render_alert_message(
    *,
    product_name: str,
    price: int,
    target_price: int,
    site: SiteKey,
    url: str,
    previous_price: int | None = None,
) -> AlertMessage:
    """Thông báo giá xuống dưới ngưỡng; `previous_price` là giá của lần báo trước (nếu có)."""
    subject = f"Giá giảm: {product_name} còn {format_vnd(price)}"
    lines = [
        f"{product_name} hiện có giá {format_vnd(price)}"
        f" (ngưỡng bạn đặt: {format_vnd(target_price)}).",
    ]
    if previous_price is not None:
        lines.append(f"Lần báo trước: {format_vnd(previous_price)}.")
    lines.append(f"Nơi bán: {site.value}")
    lines.append(f"Link: {url}")
    return AlertMessage(subject=subject, body="\n".join(lines))
