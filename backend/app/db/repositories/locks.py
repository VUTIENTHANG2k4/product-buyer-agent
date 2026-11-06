"""Khóa tư vấn (advisory lock) của PostgreSQL để tuần tự hóa việc "kiểm tra rồi tạo".

Không có ràng buộc UNIQUE cho tên danh sách hay bộ (sản phẩm, kênh, nơi nhận) của cảnh báo, nên
hai yêu cầu đồng thời cùng thấy "chưa có" rồi cùng tạo. Khóa theo khóa nghiệp vụ, giữ tới hết
transaction (`pg_advisory_xact_lock`), buộc bên sau chờ bên trước commit rồi mới đọc lại.
"""

from sqlalchemy import func
from sqlmodel import Session, select

SHOPPING_LIST_NAME_LOCK = 6701  # không gian khóa: tên danh sách mua
PRICE_ALERT_KEY_LOCK = 6702  # không gian khóa: (sản phẩm, kênh, nơi nhận) của cảnh báo


def advisory_xact_lock(session: Session, namespace: int, key: str) -> None:
    """Chờ và giữ khóa `(namespace, key)` tới hết transaction hiện tại."""
    session.execute(select(func.pg_advisory_xact_lock(namespace, func.hashtext(key))))
